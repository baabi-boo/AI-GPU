# SPDX-License-Identifier: Apache-2.0
"""Host-only launcher process ownership; no native library or GPU execution."""

from contextlib import contextmanager
import importlib
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

if __package__:
    from .test_p05_bundle import PACKAGE, ROOT, isolated_package
else:
    from test_p05_bundle import PACKAGE, ROOT, isolated_package


LAUNCH_PATH = PACKAGE / "launch.py"
_WRAPPER = r"""
import importlib.util, json, os, signal, subprocess, sys, types
signal.alarm(12)
source, package_path, script, mode = sys.argv[1:]
package = types.ModuleType('vortex_ai')
package.__path__ = [package_path]
sys.modules['vortex_ai'] = package
spec = importlib.util.spec_from_file_location('vortex_ai.launch', source)
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)
launch.verified_environment = lambda unused: dict(os.environ)
previous = signal.SIG_DFL
signal.signal(signal.SIGTERM, previous)
real_popen, children = subprocess.Popen, []
def track(*args, **kwargs):
    child = real_popen(*args, **kwargs)
    children.append(child)
    return child
launch.subprocess.Popen = track
status = launch.main(['--bundle', '/inert-host-only-bundle', '--', script, mode])
reaped = []
for child in children:
    try:
        os.waitpid(child.pid, os.WNOHANG)
    except ChildProcessError:
        reaped.append(True)
    else:
        reaped.append(False)
print(json.dumps({'event': 'result', 'status': status,
                  'restored': signal.getsignal(signal.SIGTERM) is previous,
                  'reaped': reaped}), flush=True)
raise SystemExit(status)
"""

_CHILD = r"""
import json, os, signal, sys
signal.alarm(8)
def handled(signum, frame):
    print(json.dumps({'event': 'handled'}), flush=True)
if sys.argv[1] == 'handled':
    signal.signal(signal.SIGTERM, handled)
print(json.dumps({'event': 'ready', 'pid': os.getpid()}), flush=True)
line = sys.stdin.readline()
print(json.dumps({'event': 'continued', 'input': line}), flush=True)
raise SystemExit(21)
"""


class LauncherSignalTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_package())
        self.launch = importlib.import_module("vortex_ai.launch")
        self.original_handler = signal.getsignal(signal.SIGTERM)
        self.addCleanup(signal.signal, signal.SIGTERM, self.original_handler)
        self.previous = lambda signum, frame: None
        signal.signal(signal.SIGTERM, self.previous)

    @contextmanager
    def probe(self, mode):
        with tempfile.TemporaryDirectory(prefix="p05-launcher-signals-") as directory:
            script = Path(directory) / "inert child.py"
            script.write_text(_CHILD, encoding="utf-8")
            child_pidfd = None
            child_pid = None
            process = subprocess.Popen(
                [sys.executable, "-I", "-B", "-c", _WRAPPER,
                 str(LAUNCH_PATH), str(PACKAGE), str(script), mode],
                cwd=ROOT.parent, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, bufsize=0)
            buffer = bytearray()

            def event():
                nonlocal child_pidfd, child_pid
                while b"\n" not in buffer:
                    ready, _, _ = select.select([process.stdout], [], [], 5)
                    self.assertTrue(ready, "launcher probe did not produce its next event")
                    raw = os.read(process.stdout.fileno(), 4096)
                    self.assertTrue(raw, "launcher probe closed before its next event")
                    buffer.extend(raw)
                raw, _, rest = buffer.partition(b"\n")
                buffer[:] = rest
                value = json.loads(raw)
                if value["event"] == "ready":
                    child_pid = value["pid"]
                    child_pidfd = os.pidfd_open(child_pid)
                return value

            try:
                yield process, event
            finally:
                try:
                    if child_pidfd is not None:
                        try:
                            signal.pidfd_send_signal(child_pidfd, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        finally:
                            os.close(child_pidfd)
                finally:
                    try:
                        if process.poll() is None:
                            process.kill()
                        process.wait(timeout=5)
                        # A separate negative-control runner can adopt orphaned probes.
                        if child_pid is not None:
                            try:
                                os.waitpid(child_pid, 0)
                            except ChildProcessError:
                                pass
                    finally:
                        for stream in (process.stdin, process.stdout, process.stderr):
                            stream.close()

    def test_pid_directed_sigterm_reaches_child_and_reaps_before_return(self):
        with self.probe("default") as (process, event):
            self.assertEqual(event()["event"], "ready")
            os.kill(process.pid, signal.SIGTERM)
            result = event()
            self.assertEqual(result, {"event": "result", "status": 143,
                                      "restored": True, "reaped": [True]})
            self.assertEqual(process.wait(timeout=5), 143)
            self.assertEqual(process.stdout.read(), b"")
            self.assertEqual(process.stderr.read(), b"")

    def test_handled_sigterm_waits_for_child_actual_exit(self):
        with self.probe("handled") as (process, event):
            self.assertEqual(event()["event"], "ready")
            os.kill(process.pid, signal.SIGTERM)
            self.assertEqual(event(), {"event": "handled"})
            self.assertIsNone(process.poll())
            process.stdin.write(b"finish\n")
            self.assertEqual(event(), {"event": "continued", "input": "finish\n"})
            self.assertEqual(event(), {"event": "result", "status": 21,
                                       "restored": True, "reaped": [True]})
            self.assertEqual(process.wait(timeout=5), 21)
            self.assertEqual(process.stderr.read(), b"")

    def test_signal_during_process_assignment_is_deferred_until_child_owned(self):
        events = []
        child = mock.Mock()

        def start(*args, **kwargs):
            handler = signal.getsignal(signal.SIGTERM)
            self.assertIsNot(handler, self.previous)
            handler(signal.SIGTERM, None)
            child.send_signal.assert_not_called()
            child.wait.assert_not_called()
            events.append("returned-child")
            return child

        child.send_signal.side_effect = lambda signum: events.append(("forward", signum))
        child.wait.side_effect = lambda **kwargs: events.append("wait") or -signal.SIGTERM
        with mock.patch.object(self.launch.subprocess, "Popen", side_effect=start):
            self.assertEqual(self.launch._run_child(["inert"], env={}), -signal.SIGTERM)
        self.assertEqual(events, ["returned-child", ("forward", signal.SIGTERM), "wait"])
        self.assertIs(signal.getsignal(signal.SIGTERM), self.previous)

    def test_previous_handler_is_restored_after_real_child_success(self):
        result = self.launch._run_child(
            [sys.executable, "-I", "-B", "-c", "raise SystemExit(37)"],
            env=dict(os.environ))
        self.assertEqual(result, 37)
        self.assertIs(signal.getsignal(signal.SIGTERM), self.previous)

    def test_previous_handler_is_restored_after_spawn_error(self):
        failure = OSError("injected process creation failure")
        with mock.patch.object(self.launch.subprocess, "Popen", side_effect=failure):
            with self.assertRaises(OSError) as caught:
                self.launch._run_child(["inert"], env={})
        self.assertIs(caught.exception, failure)
        self.assertIs(signal.getsignal(signal.SIGTERM), self.previous)

    def test_wait_error_kills_reaps_and_preserves_first_failure_and_handler(self):
        failure = OSError("injected wait failure")
        real_popen = subprocess.Popen
        children = []

        class FailFirstWait(real_popen):
            failed = False

            def wait(self, *args, **kwargs):
                if not self.failed:
                    self.failed = True
                    raise failure
                return super().wait(*args, **kwargs)

        def start(*args, **kwargs):
            child = FailFirstWait(*args, **kwargs)
            children.append(child)
            return child

        try:
            with mock.patch.object(self.launch.subprocess, "Popen", side_effect=start):
                with self.assertRaises(OSError) as caught:
                    self.launch._run_child(
                        [sys.executable, "-I", "-B", "-c",
                         "import signal; signal.alarm(8); signal.pause()"], env=dict(os.environ))
            self.assertIs(caught.exception, failure)
            self.assertEqual(len(children), 1)
            self.assertEqual(children[0].returncode, -signal.SIGKILL)
            with self.assertRaises(ChildProcessError):
                os.waitpid(children[0].pid, os.WNOHANG)
            self.assertIs(signal.getsignal(signal.SIGTERM), self.previous)
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                real_popen.wait(child, timeout=5)

    def test_pending_signal_after_child_exit_preserves_collected_status(self):
        child = subprocess.Popen([sys.executable, "-I", "-B", "-c", "raise SystemExit(17)"])
        try:
            self.assertEqual(child.wait(timeout=5), 17)

            def start(*args, **kwargs):
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
                return child

            with mock.patch.object(self.launch.subprocess, "Popen", side_effect=start):
                self.assertEqual(self.launch._run_child(["inert"], env={}), 17)
            self.assertIs(signal.getsignal(signal.SIGTERM), self.previous)
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)

    def test_worker_thread_rejects_before_spawning_or_changing_signal_state(self):
        observed = []

        def run():
            try:
                self.launch._run_child(["inert"], env={})
            except BaseException as error:
                observed.append(error)

        with mock.patch.object(self.launch.subprocess, "Popen") as start:
            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            start.assert_not_called()
        self.assertEqual(len(observed), 1)
        self.assertIsInstance(observed[0], RuntimeError)
        self.assertIn("main thread", str(observed[0]))
        self.assertIs(signal.getsignal(signal.SIGTERM), self.previous)


if __name__ == "__main__":
    unittest.main()
