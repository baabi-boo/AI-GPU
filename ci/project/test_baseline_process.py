# Licensed under the Apache License, Version 2.0.
"""Small subprocess regressions for bounded baseline execution."""

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
class BoundedProcessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.log = self.root / "command.log"
        self.processes = []
        self.addCleanup(self.cleanup_processes)
        self.original_popen = subprocess.Popen
        self.popen_patch = mock.patch.object(
            baseline_process.subprocess, "Popen", side_effect=self.start_process)
        self.popen = self.popen_patch.start()
        self.addCleanup(self.popen_patch.stop)

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

    def run_script(self, script="print('ready', flush=True)", **limits):
        options = {"timeout_seconds": 3, "min_free_bytes": 1,
                   "max_log_bytes": 4096, "max_rss_bytes": 256 * 1024 ** 2,
                   "poll_seconds": 0.01}
        options.update(limits)
        return baseline_process.run_bounded(
            [sys.executable, "-c", script], self.root, os.environ.copy(),
            self.log, **options)

    def assert_log_integrity(self, result, expected=None):
        content = self.log.read_bytes()
        self.assertEqual(result["log_size_bytes"], len(content))
        self.assertEqual(result["log_sha256"], hashlib.sha256(content).hexdigest())
        if expected is not None:
            self.assertEqual(content, expected)

    def assert_not_live(self, pid):
        try:
            fields = Path("/proc", str(pid), "stat").read_text().rsplit(") ", 1)[1].split()
        except FileNotFoundError:
            return
        self.assertIn(fields[0], ("Z", "X"), "subprocess remains alive: " + str(pid))

    def assert_stopped(self, result):
        self.assertTrue(result["cleanup_complete"])
        for process in self.processes:
            self.assertIsNotNone(process.poll())
            self.assert_not_live(process.pid)
        if self.log.exists():
            for line in self.log.read_text().splitlines():
                if line.startswith("CHILD "):
                    self.assert_not_live(int(line.split()[1]))

    def test_success_combines_streams_and_hashes_retained_bytes(self):
        result = self.run_script("import os; os.write(1, b'out\\n'); os.write(2, b'err\\n')")
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["exit_code"], 0)
        self.assertIsNone(result["reason"])
        self.assert_log_integrity(result, b"out\nerr\n")
        self.assert_stopped(result)

    def test_nonzero_exit_preserves_failure_and_output(self):
        result = self.run_script("import sys; print('failure detail', flush=True); sys.exit(7)")
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["exit_code"], 7)
        self.assertEqual(result["reason"], "nonzero_exit")
        self.assert_log_integrity(result, b"failure detail\n")
        self.assert_stopped(result)

    def test_exact_log_limit_is_allowed(self):
        result = self.run_script("import os; os.write(1, b'x' * 64)", max_log_bytes=64)
        self.assertEqual(result["outcome"], "pass")
        self.assert_log_integrity(result, b"x" * 64)

    def test_output_overflow_is_capped_and_failed(self):
        result = self.run_script("import os; os.write(1, b'x' * 20000)", max_log_bytes=128)
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["reason"], "log_limit")
        self.assert_log_integrity(result, b"x" * 128)
        self.assert_stopped(result)

    def test_timeout_kills_term_resistant_descendant(self):
        script = """
import os, signal, time
reader, writer = os.pipe()
pid = os.fork()
if pid == 0:
    os.close(reader)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    print('CHILD', os.getpid(), flush=True)
    os.write(writer, b'1')
    time.sleep(30)
else:
    os.close(writer)
    os.read(reader, 1)
    print('parent ready', flush=True)
    time.sleep(30)
"""
        result = self.run_script(script, timeout_seconds=0.5)
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["reason"], "timeout")
        self.assertLess(result["duration_seconds"], 4)
        self.assertIn(b"parent ready", self.log.read_bytes())
        self.assert_log_integrity(result)
        self.assert_stopped(result)

    def test_parent_exit_does_not_pass_with_orphan_holding_stdout(self):
        script = """
import os, signal, time
reader, writer = os.pipe()
pid = os.fork()
if pid == 0:
    os.close(reader)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    print('CHILD', os.getpid(), flush=True)
    os.write(writer, b'1')
    time.sleep(30)
else:
    os.close(writer)
    os.read(reader, 1)
    os._exit(0)
"""
        result = self.run_script(script)
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["reason"], "descendants_after_exit")
        self.assertLess(result["duration_seconds"], 4)
        self.assert_log_integrity(result)
        self.assert_stopped(result)

    def test_closing_stdout_early_does_not_disable_timeout(self):
        result = self.run_script(
            "import os,time; os.close(1); os.close(2); time.sleep(30)",
            timeout_seconds=0.2)
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["reason"], "timeout")
        self.assert_log_integrity(result, b"")
        self.assert_stopped(result)

    def test_existing_log_is_never_overwritten(self):
        self.log.write_bytes(b"prior evidence")
        with self.assertRaises(ValueError):
            self.run_script()
        self.popen.assert_not_called()
        self.assertEqual(self.log.read_bytes(), b"prior evidence")

    def test_log_symlink_is_never_followed(self):
        target = self.root / "target"
        target.write_bytes(b"protected")
        self.log.symlink_to(target)
        with self.assertRaises(ValueError):
            self.run_script()
        self.popen.assert_not_called()
        self.assertEqual(target.read_bytes(), b"protected")

    def test_parent_directory_symlink_is_rejected(self):
        actual = self.root / "actual"
        actual.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(actual, target_is_directory=True)
        self.log = alias / "command.log"
        with self.assertRaises(ValueError):
            self.run_script()
        self.popen.assert_not_called()
        self.assertFalse((actual / "command.log").exists())

    def test_invalid_budgets_reject_before_launch(self):
        invalid = {
            "timeout_seconds": (0, -1, True, float("nan"), float("inf"), "1"),
            "poll_seconds": (0, -1, True, float("nan"), float("inf")),
            "min_free_bytes": (0, -1, True, 1.5),
            "max_log_bytes": (0, -1, True, 1.5),
            "max_rss_bytes": (0, -1, True, 1.5),
        }
        for name, values in invalid.items():
            for value in values:
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    self.run_script(**{name: value})
        self.popen.assert_not_called()
        self.assertFalse(self.log.exists())

    def test_prelaunch_disk_shortage_is_blocked_without_a_log(self):
        with mock.patch.object(baseline_process, "_disk_has_reserve", return_value=False):
            result = self.run_script()
        self.assertEqual(result["outcome"], "blocked")
        self.assertEqual(result["reason"], "disk_reserve")
        self.assertIsNone(result["exit_code"])
        self.assertIsNone(result["log_sha256"])
        self.popen.assert_not_called()
        self.assertFalse(self.log.exists())

    def test_prelaunch_missing_resource_inventory_is_blocked(self):
        with mock.patch.object(baseline_process, "_group_snapshot", side_effect=OSError):
            result = self.run_script()
        self.assertEqual(result["outcome"], "blocked")
        self.assertEqual(result["reason"], "resource_inventory_unavailable")
        self.popen.assert_not_called()
        self.assertFalse(self.log.exists())

    def test_runtime_disk_shortage_stops_the_command(self):
        with mock.patch.object(baseline_process, "_disk_has_reserve", side_effect=[True, False]):
            result = self.run_script("import time; time.sleep(30)")
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["reason"], "disk_reserve")
        self.assertIsNotNone(result["exit_code"])
        self.assert_log_integrity(result)
        self.assert_stopped(result)

    def test_runtime_rss_breach_stops_the_command(self):
        snapshot = baseline_process._group_snapshot

        def inflated_rss(group):
            rss, live = snapshot(group)
            if group != os.getpgrp() and live:
                rss = 257 * 1024 ** 2
            return rss, live

        with mock.patch.object(baseline_process, "_group_snapshot", side_effect=inflated_rss):
            result = self.run_script("import time; time.sleep(30)")
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["reason"], "memory_limit")
        self.assertEqual(result["peak_rss_bytes"], 257 * 1024 ** 2)
        self.assert_log_integrity(result)
        self.assert_stopped(result)

    def test_all_explicit_resource_locations_are_checked(self):
        other = self.root / "other-filesystem"
        other.mkdir()
        with mock.patch.object(baseline_process, "_disk_has_reserve", return_value=False) as check:
            result = self.run_script(resource_paths=(other,))
        self.assertEqual(result["outcome"], "blocked")
        self.assertIn(other, check.call_args.args[0])
        self.assertIn(self.root, check.call_args.args[0])

    def test_launch_failure_is_blocked_and_retains_empty_log(self):
        result = baseline_process.run_bounded(
            [str(self.root / "missing-executable")], self.root,
            os.environ.copy(), self.log, min_free_bytes=1)
        self.assertEqual(result["outcome"], "blocked")
        self.assertEqual(result["reason"], "launch_failed")
        self.assertIsNone(result["exit_code"])
        self.assert_log_integrity(result, b"")

    def test_sigterm_interrupts_and_restores_original_handlers(self):
        before = {number: signal.getsignal(number)
                  for number in (signal.SIGINT, signal.SIGTERM)}
        result = self.run_script(
            "import os,signal,time; print('interrupting',flush=True); "
            "os.kill(os.getppid(),signal.SIGTERM); time.sleep(30)")
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["reason"], "interrupted_signal_" + str(signal.SIGTERM))
        self.assertEqual(before, {number: signal.getsignal(number) for number in before})
        self.assert_log_integrity(result, b"interrupting\n")
        self.assert_stopped(result)

    def test_keyboard_interrupt_cleans_up_a_started_child(self):
        with mock.patch.object(baseline_process, "_disk_has_reserve",
                               side_effect=[True, KeyboardInterrupt()]):
            result = self.run_script("import time; time.sleep(30)")
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["reason"], "interrupted")
        self.assert_log_integrity(result)
        self.assert_stopped(result)

    def assert_signal_at_completion(self, boundary, number):
        before = {item: signal.getsignal(item)
                  for item in (signal.SIGINT, signal.SIGTERM)}
        self.log = self.root / (boundary + "-" + str(number) + ".log")
        current = []
        delivered = []
        original_read = os.read

        def deliver():
            if not delivered:
                delivered.append(number)
                os.kill(os.getpid(), number)

        def exited_process(*args, **kwargs):
            process = self.start_process(*args, **kwargs)
            process.wait(timeout=3)
            current.append(process)
            if boundary == "wait":
                original_wait = process.wait

                def wait(*wait_args, **wait_kwargs):
                    code = original_wait(*wait_args, **wait_kwargs)
                    deliver()
                    return code

                process.wait = wait
            elif boundary == "close":
                original_close = process.stdout.close

                def close():
                    original_close()
                    deliver()

                process.stdout.close = close
            return process

        def read(descriptor, size):
            chunk = original_read(descriptor, size)
            if (boundary == "eof" and not chunk and current
                    and descriptor == current[0].stdout.fileno()):
                deliver()
            return chunk

        self.popen.side_effect = exited_process
        with mock.patch.object(baseline_process.os, "read", side_effect=read):
            result = self.run_script("print('complete', flush=True)")
        self.assertEqual(delivered, [number])
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["reason"], "interrupted_signal_" + str(number))
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(before, {item: signal.getsignal(item) for item in before})
        self.assert_log_integrity(result, b"complete\n")
        self.assert_stopped(result)

    def test_completion_signals_are_not_swallowed(self):
        for boundary in ("eof", "wait", "close"):
            for number in (signal.SIGINT, signal.SIGTERM):
                with self.subTest(boundary=boundary, signal=number):
                    self.assert_signal_at_completion(boundary, number)


if __name__ == "__main__":
    unittest.main()
