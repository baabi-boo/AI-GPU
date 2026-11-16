# Licensed under the Apache License, Version 2.0.
"""Real cancellation of small Python probes; no vendor or GPU execution."""

from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from baseline_inventory import _probe
from baseline_process import run_bounded
from xrt_signals import terminate_as_interrupt


HERE = Path(__file__).resolve().parent
SLEEPING_CHILD = [sys.executable, "-c", "import time; time.sleep(8)"]


@contextmanager
def _observe_child(directory, popen):
    selector_type = selectors.DefaultSelector

    class ReadySelector(selector_type):
        def register(self, *args, **kwargs):
            key = super().register(*args, **kwargs)
            # The caller owns its Popen object before cancellation is released.
            (directory / "ready").touch()
            return key

    def start(*args, **kwargs):
        process = popen(*args, **kwargs)
        (directory / "probe.pid").write_text(str(process.pid), encoding="ascii")
        return process

    with mock.patch.object(subprocess, "Popen", side_effect=start), mock.patch.object(
            selectors, "DefaultSelector", ReadySelector):
        yield


def _runner_scenario(directory, boundary):
    import baseline_host
    import xrt_baseline
    from test_xrt_baseline import RunnerFixture

    popen = subprocess.Popen
    fixture = RunnerFixture()
    try:
        fixture.setUp()
        args, paths, report = fixture.plan()
        if report["outcome"] != "pass":
            raise AssertionError(report["blockers"])
        host_bin = directory / "host-bin"
        host_bin.mkdir()
        compiler = host_bin / "gcc"
        compiler.write_text("#!" + sys.executable + "\nimport time\ntime.sleep(8)\n",
                            encoding="utf-8")
        compiler.chmod(0o700)

        def collect(environment):
            if boundary == "between" and not fixture.calls:
                return copy.deepcopy(fixture.host_record)
            return baseline_host.collect_host(environment)

        fixture.host_observation.side_effect = collect
        with mock.patch.dict(os.environ, {"PATH": str(host_bin)}), _observe_child(directory, popen):
            report = xrt_baseline.execute_run(args, report, paths)
        return {"returned": report, "retained": json.loads(
            (fixture.fixture.output / "report.json").read_text(encoding="utf-8")),
            "calls": [call["id"] for call in fixture.calls]}
    finally:
        fixture.doCleanups()


def _subprocess_scenario(directory, scenario):
    directory = Path(directory)
    previous = signal.getsignal(signal.SIGTERM)
    original_sigint = signal.getsignal(signal.SIGINT)
    if scenario == "probe":
        result = {"interrupted": False}
        try:
            with terminate_as_interrupt(), _observe_child(directory, subprocess.Popen):
                _probe(SLEEPING_CHILD, timeout=5)
        except KeyboardInterrupt:
            result["interrupted"] = True
    elif scenario == "bounded":
        with terminate_as_interrupt():
            outer_handler = signal.getsignal(signal.SIGTERM)
            with _observe_child(directory, subprocess.Popen):
                result = run_bounded(
                    SLEEPING_CHILD, directory, os.environ.copy(), directory / "command.log",
                    timeout_seconds=5, min_free_bytes=1, max_log_bytes=4096,
                    max_rss_bytes=256 * 1024**2, poll_seconds=0.01)
            result["outer_handler_restored"] = signal.getsignal(signal.SIGTERM) is outer_handler
            result["outer_interrupt_works"] = False
            try:
                os.kill(os.getpid(), signal.SIGTERM)
            except KeyboardInterrupt:
                result["outer_interrupt_works"] = True
    else:
        result = _runner_scenario(directory, scenario)
    result["handler_restored"] = signal.getsignal(signal.SIGTERM) is previous
    result["sigint_unchanged"] = signal.getsignal(signal.SIGINT) is original_sigint
    (directory / "result.json").write_text(json.dumps(result), encoding="utf-8")


class TerminateAsInterruptTests(unittest.TestCase):
    def test_restores_custom_handler_on_normal_and_exceptional_exit(self):
        previous = signal.getsignal(signal.SIGTERM)
        self.addCleanup(signal.signal, signal.SIGTERM, previous)
        original_sigint = signal.getsignal(signal.SIGINT)

        def handler(number, frame):
            raise AssertionError("previous handler was called")

        signal.signal(signal.SIGTERM, handler)
        with terminate_as_interrupt():
            self.assertIsNot(signal.getsignal(signal.SIGTERM), handler)
            self.assertIs(signal.getsignal(signal.SIGINT), original_sigint)
        self.assertIs(signal.getsignal(signal.SIGTERM), handler)
        with self.assertRaisesRegex(RuntimeError, "fixture failure"):
            with terminate_as_interrupt():
                raise RuntimeError("fixture failure")
        self.assertIs(signal.getsignal(signal.SIGTERM), handler)

    def test_nested_scopes_and_reused_decorator_restore_handlers(self):
        original = signal.getsignal(signal.SIGTERM)
        self.addCleanup(signal.signal, signal.SIGTERM, original)

        @terminate_as_interrupt()
        def observed_handler():
            return signal.getsignal(signal.SIGTERM)

        for _ in range(2):
            with terminate_as_interrupt():
                outer = signal.getsignal(signal.SIGTERM)
                self.assertIsNot(observed_handler(), outer)
                self.assertIs(signal.getsignal(signal.SIGTERM), outer)
            self.assertIs(signal.getsignal(signal.SIGTERM), original)

    def test_worker_thread_is_rejected_before_entering_body(self):
        errors = []
        entered = []
        previous = signal.getsignal(signal.SIGTERM)

        def worker():
            try:
                with terminate_as_interrupt():
                    entered.append(True)
            except ValueError as error:
                errors.append(str(error))

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(entered, [])
        self.assertEqual(errors, ["SIGTERM interruption handling requires the main thread"])
        self.assertIs(signal.getsignal(signal.SIGTERM), previous)


@unittest.skipUnless(os.name == "posix" and Path("/proc/self/stat").exists(),
                     "process cancellation requires Linux /proc")
class XrtCancellationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.processes = []
        self.addCleanup(self.cleanup_processes)

    def cleanup_processes(self):
        for process, directory in self.processes:
            try:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=3)
            for stream in (process.stdout, process.stderr):
                stream.close()
            marker = directory / "probe.pid"
            if marker.exists():
                try:
                    os.killpg(int(marker.read_text(encoding="ascii")), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def interrupted_scenario(self, scenario):
        directory = self.root / str(len(self.processes))
        directory.mkdir()
        code = ("import sys; from test_xrt_cancellation import _subprocess_scenario; "
                "_subprocess_scenario(sys.argv[1], sys.argv[2])")
        process = subprocess.Popen(
            [sys.executable, "-c", code, str(directory), scenario], cwd=HERE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        self.processes.append((process, directory))
        deadline = time.monotonic() + 4
        while not (directory / "ready").exists():
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=1)
                self.fail("cancellation scenario exited before its child: " + scenario
                          + "\n" + (stdout + stderr).decode("utf-8", "replace"))
            if time.monotonic() >= deadline:
                self.fail("cancellation scenario did not reach a live child: " + scenario)
            time.sleep(0.01)
        child_pid = int((directory / "probe.pid").read_text(encoding="ascii"))
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0, (stdout + stderr).decode("utf-8", "replace"))
        self.assertFalse(Path("/proc", str(child_pid)).exists(),
                         "cancelled probe was not reaped: " + str(child_pid))
        result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
        self.assertIs(result["handler_restored"], True)
        self.assertIs(result["sigint_unchanged"], True)
        return result

    def test_sigterm_during_real_probe_reaps_child_and_restores_handler(self):
        self.assertIs(self.interrupted_scenario("probe")["interrupted"], True)

    def test_bounded_command_restores_enclosing_cancellation_handler(self):
        result = self.interrupted_scenario("bounded")
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["reason"], "interrupted_signal_" + str(signal.SIGTERM))
        self.assertIs(result["cleanup_complete"], True)
        self.assertIs(result["outer_handler_restored"], True)
        self.assertIs(result["outer_interrupt_works"], True)

    def test_host_probe_cancellation_retains_finished_failure_without_acceptance(self):
        for boundary, commands in (("before", []), ("between", ["configure"])):
            with self.subTest(boundary=boundary):
                result = self.interrupted_scenario(boundary)
                self.assertEqual(result["calls"], commands)
                for report in (result["returned"], result["retained"]):
                    self.assertEqual(report["outcome"], "fail")
                    self.assertEqual(report["reason"], "execution interrupted")
                    self.assertEqual(report["state"], "finished")
                    self.assertIn("finished_at", report)
                    self.assertNotIn("active_command", report)
                    self.assertEqual([entry["id"] for entry in report["commands"]], commands)
                    self.assertIs(report["phase_complete"], False)
                    self.assertEqual(report["acceptance"], "not_evaluated")
                    self.assertNotEqual(report["integration"]["outcome"], "pass")
                    self.assertIsNone(report["integration"]["exit_code"])


if __name__ == "__main__":
    unittest.main()
