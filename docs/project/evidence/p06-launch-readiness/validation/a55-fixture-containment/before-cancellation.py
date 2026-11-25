# SPDX-License-Identifier: Apache-2.0
"""Real qualified-warm CLI cancellation with inert and synthetic host children."""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from baseline_process import run_bounded
import p06_qualified_warm_execute as runner


HERE = Path(__file__).resolve().parent
PREFLIGHT = runner.preflight
FALSE_CLAIMS = ("native_preflight_passed", "native_lifetime_passed",
    "dependency_source_to_loaded_binary_verified", "counter_qualification_passed",
    "qualified_warm_passed", *PREFLIGHT.manifest.FALSE_CLAIMS)


def _arguments(args):
    return ["run", *(item for name, value in vars(args).items()
        if name not in ("mode", "verilator") and value is not None
        for item in ("--" + name.replace("_", "-"), str(value)))]


def _scenario(directory, boundary):
    from test_p06_qualified_warm_runner import FIRST, WarmHarness

    directory = Path(directory)
    previous = signal.getsignal(signal.SIGTERM)
    sigint = signal.getsignal(signal.SIGINT)
    observations = []
    paused = False
    with WarmHarness() as fixture:
        receipt = fixture.paths["output"] / "report.json"
        write = PREFLIGHT.base._write_json

        def pause():
            nonlocal paused
            paused = True
            (directory / "checkpoint.json").write_bytes(receipt.read_bytes())
            (directory / "ready").touch()
            signal.pause()
            raise AssertionError("SIGTERM did not interrupt the selected boundary")

        def snapshot(*args, **kwargs):
            if boundary == "source" and observations and not paused:
                pause()
            return fixture.source_snapshot(*args, **kwargs)

        def checkpoint(path, report):
            write(path, report)
            if (boundary == "partial" and not paused and Path(path) == receipt
                    and report["processes"] and report["processes"][-1]["id"] == FIRST
                    and report["processes"][-1]["outcome"] == "pass"):
                pause()

        def command(argv, cwd, environment, log, **limits):
            if paused:
                raise AssertionError("qualified-warm execution continued after cancellation")
            if observations:
                return fixture.command(argv, cwd, environment, log, **limits)
            outer = signal.getsignal(signal.SIGTERM)
            code = ("import os,pathlib,sys,time; "
                "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()),encoding='ascii'); "
                "print('inert qualified-warm cancellation probe',flush=True); ")
            if boundary == "bounded":
                code += "pathlib.Path(sys.argv[2]).touch(); time.sleep(30)"
            result = run_bounded([sys.executable, "-I", "-B", "-c", code,
                str(directory / "child.pid"), str(directory / "ready")],
                cwd, environment, log, **dict(limits, min_free_bytes=1,
                    max_rss_bytes=128 * 1024**2))
            observations.append({"result": result,
                "outer_handler_installed": callable(outer),
                "outer_handler_restored": signal.getsignal(signal.SIGTERM) is outer})
            return result

        PREFLIGHT.run_bounded.side_effect = command
        with mock.patch.object(PREFLIGHT.base, "resolve_paths", return_value=fixture.paths), \
                mock.patch.object(PREFLIGHT, "source_snapshot", side_effect=snapshot), \
                mock.patch.object(PREFLIGHT.base, "_write_json", side_effect=checkpoint):
            status = runner.main(_arguments(fixture.args))
        report = json.loads(receipt.read_text())
        result = {"main_status": status, "report": report, "observations": observations,
            "handler_restored": signal.getsignal(signal.SIGTERM) is previous,
            "sigint_unchanged": signal.getsignal(signal.SIGINT) is sigint,
            "launches": fixture.launches(),
            "log": (fixture.paths["output"] / report["commands"][0]["log"]).read_text()}
        (directory / "result.json").write_text(json.dumps(result), encoding="utf-8")
    return status


@unittest.skipUnless(os.name == "posix" and Path("/proc/self/stat").exists(),
                     "qualified-warm cancellation requires Linux /proc")
class QualifiedWarmCancellationTests(unittest.TestCase):
    def test_forced_exit_keeps_fixture_owned_by_parent_cleanup(self):
        code = """
import os
from pathlib import Path
import signal
import sys
from unittest import mock
import test_p06_qualified_warm_cancellation as cancellation

def stop_after_fixture_setup(argv):
    paths = cancellation.PREFLIGHT.base.resolve_paths(None)
    Path(sys.argv[1], 'fixture-root').write_text(str(paths['source'].parent), encoding='utf-8')
    os.kill(os.getpid(), signal.SIGKILL)

with mock.patch.object(cancellation.runner, 'main', side_effect=stop_after_fixture_setup):
    cancellation._scenario(sys.argv[1], 'source')
"""
        with tempfile.TemporaryDirectory(prefix="p06-warm-forced-exit-") as temporary:
            directory = Path(temporary).resolve()
            result = subprocess.run([sys.executable, "-B", "-c", code, str(directory)],
                cwd=HERE, env=dict(os.environ, TMPDIR=str(directory), PYTHONDONTWRITEBYTECODE="1"),
                capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, -signal.SIGKILL, result.stdout + result.stderr)
            fixture_root = Path((directory / "fixture-root").read_text(encoding="utf-8"))
            self.addCleanup(shutil.rmtree, fixture_root, ignore_errors=True)
            self.assertTrue(fixture_root.is_dir(), "forced exit must bypass fixture cleanup")
            self.assertTrue(fixture_root.is_relative_to(directory),
                "fixture escaped the parent's temporary directory: " + str(fixture_root))
        self.assertFalse(fixture_root.exists(), "parent cleanup left the child fixture behind")

    def interrupted(self, boundary):
        with tempfile.TemporaryDirectory(prefix="p06-warm-cancellation-") as temporary:
            directory = Path(temporary)
            code = ("import sys; from test_p06_qualified_warm_cancellation import _scenario; "
                    "sys.exit(_scenario(sys.argv[1],sys.argv[2]))")
            process = subprocess.Popen([sys.executable, "-B", "-c", code, str(directory), boundary],
                cwd=HERE, env=dict(os.environ, TMPDIR=str(directory), PYTHONDONTWRITEBYTECODE="1"),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            try:
                deadline = time.monotonic() + 10
                while not (directory / "ready").exists():
                    if process.poll() is not None:
                        output = b"".join(process.communicate(timeout=1))
                        self.fail("scenario exited before readiness: " + output.decode("utf-8", "replace"))
                    self.assertLess(time.monotonic(), deadline, "cancellation readiness timeout")
                    time.sleep(0.01)
                child_pid = int((directory / "child.pid").read_text(encoding="ascii"))
                if boundary != "bounded":
                    self.assertFalse(Path("/proc", str(child_pid)).exists(), "completed child was not reaped")
                    checkpoint = json.loads((directory / "checkpoint.json").read_text())
                    self.assertEqual(checkpoint["state"], "running")
                    self.assertEqual(checkpoint["commands"][-1]["exit_code"], 0)
                    self.assertTrue(checkpoint["commands"][-1]["cleanup_complete"])
                process.send_signal(signal.SIGTERM)
                output = b"".join(process.communicate(timeout=10))
                self.assertEqual(process.returncode, 1, output.decode("utf-8", "replace"))
                self.assertFalse(Path("/proc", str(child_pid)).exists(), "cancelled child was not reaped")
                result = json.loads((directory / "result.json").read_text())
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
                for stream in (process.stdout, process.stderr):
                    stream.close()
                marker = directory / "child.pid"
                if marker.exists():
                    try:
                        os.killpg(int(marker.read_text(encoding="ascii")), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        self.assertEqual(result["main_status"], 1)
        self.assertTrue(result["handler_restored"])
        self.assertTrue(result["sigint_unchanged"])
        self.assertEqual(len(result["observations"]), 1)
        observation = result["observations"][0]
        self.assertTrue(observation["outer_handler_installed"])
        self.assertTrue(observation["outer_handler_restored"])
        self.assertTrue(observation["result"]["process_started"])
        self.assertTrue(observation["result"]["cleanup_complete"])
        report = result["report"]
        self.assertEqual(report["state"], "finished")
        self.assertEqual(report["outcome"], "fail")
        self.assertTrue(report["retained_files_stable"])
        for field in FALSE_CLAIMS:
            self.assertIs(report[field], False, field)
        self.assertEqual(result["log"], "inert qualified-warm cancellation probe\n")
        return result

    def test_sigterm_during_source_observation_finalizes_non_native_failure(self):
        result = self.interrupted("source")
        report = result["report"]
        self.assertEqual(report["reason"], "interrupted")
        self.assertEqual(report["native_execution"], "not_run")
        self.assertEqual(report["completed_counts"]["processes"], 0)
        self.assertEqual([row["id"] for row in report["commands"]], ["version-gpp"])
        self.assertEqual(result["launches"], [])

    def test_sigterm_after_synthetic_native_process_preserves_partial_population(self):
        from test_p06_qualified_warm_runner import FIRST

        result = self.interrupted("partial")
        report = result["report"]
        self.assertEqual(report["reason"], "interrupted")
        self.assertEqual(report["native_execution"], "run")
        self.assertEqual(report["completed_counts"]["processes"], 1)
        self.assertEqual(report["completed_counts"]["launches"], 33)
        self.assertEqual(result["launches"], [FIRST])
        self.assertEqual(report["processes"][0]["outcome"], "pass")

    def test_sigterm_inside_bounded_child_preserves_monitor_cleanup(self):
        result = self.interrupted("bounded")
        report = result["report"]
        self.assertEqual(report["native_execution"], "not_run")
        self.assertEqual(len(report["commands"]), 1)
        command = report["commands"][0]
        self.assertEqual(command["reason"], "interrupted_signal_" + str(signal.SIGTERM))
        self.assertNotEqual(command["exit_code"], 0)
        self.assertTrue(command["cleanup_complete"])

    def test_cli_restores_enclosing_handler_on_parser_unwind(self):
        def enclosing(number, frame):
            raise AssertionError("enclosing handler must not run")

        previous = signal.signal(signal.SIGTERM, enclosing)
        try:
            with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                runner.main(["--help"])
            self.assertIs(signal.getsignal(signal.SIGTERM), enclosing)
        finally:
            signal.signal(signal.SIGTERM, previous)

    def test_cli_helper_inventory_still_matches_the_complete_reader(self):
        code = """
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
from unittest import mock
sys.path.insert(0, sys.argv[1])
import p06_qualified_warm_execute as runner
with tempfile.TemporaryDirectory(prefix='warm-cli-inventory-') as temporary:
    root = Path(temporary)
    (root / 'tools').mkdir()
    argv = ['run', '--source-dir', str(runner.preflight.ROOT),
        '--tools-dir', str(root / 'tools'), '--work-dir', str(root / 'work'),
        '--output', str(root / 'output'), '--expected-revision', 'a' * 40,
        '--dependency-receipt', str(root / 'dependency.json'),
        '--dependency-receipt-sha256', 'd' * 64,
        '--counter-qualification', str(root / 'proof.json'),
        '--counter-qualification-sha256', 'c' * 64,
        '--diagnostic-archive', str(root / 'diagnostic.zip'),
        '--diagnostic-archive-sha256', 'd' * 64,
        '--control-archive', str(root / 'control.zip'),
        '--control-archive-sha256', 'c' * 64]
    resources = {'available_memory_bytes': runner.preflight.BUDGET['max_rss_bytes'],
        'free_disk_bytes': {'synthetic': runner.preflight.BUDGET['min_free_bytes']}}
    with mock.patch.object(runner.preflight.base, '_resources', return_value=resources), \\
            mock.patch.object(runner.preflight, 'run_bounded',
                side_effect=AssertionError('no child may start')) as monitor, \\
            redirect_stdout(io.StringIO()):
        status = runner.main(argv)
    monitor.assert_not_called()
    report = json.loads((root / 'output/report.json').read_text())
    actual = {row['path'] for row in runner.preflight.loaded_helpers()}
import p06_qualified_warm_replay as replay
expected = set(replay.RUNNER_HELPERS)
assert status == 1 and report['state'] == 'finished'
assert report['native_execution'] == 'not_run'
assert actual == expected, (sorted(actual - expected), sorted(expected - actual))
"""
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(HERE)],
            capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
