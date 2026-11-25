# SPDX-License-Identifier: Apache-2.0
"""Real dependency CLI cancellation with bounded local Python children only."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from baseline_process import run_bounded
import p06_dependency_build as build
import p06_dependency_contract as contract


HERE = Path(__file__).resolve().parent
CHILD_LOG = "local dependency cancellation probe\n"


def _scenario(directory, boundary):
    directory = Path(directory)
    workspace = directory / "workspace"
    (workspace / "evidence").mkdir(parents=True)
    output = workspace / "evidence/dependency-build"
    previous = signal.getsignal(signal.SIGTERM)
    sigint = signal.getsignal(signal.SIGINT)
    observations, producers = [], []
    paused = False
    execute, save = build.Builder.execute, build.Builder.save
    stable = build.Builder.stable
    records = build.Builder._retain_record_inventory
    retained = build.Builder.retained_inventory

    def pause(producer):
        nonlocal paused
        paused = True
        (directory / "checkpoint.json").write_text(json.dumps(producer.report))
        (directory / "ready").touch()
        signal.pause()
        raise AssertionError("SIGTERM did not interrupt the selected boundary")

    def executing(producer):
        producers.append(producer)
        return execute(producer)

    def source(_):
        if boundary == "inert-verification":
            return {"revision": "1" * 40}
        producer = producers[0]
        if boundary == "source":
            pause(producer)
        producer.command("local-child", [sys.executable, "-I", "-B", "-c", "pass"],
                         workspace, timeout=5)
        if boundary == "after-child":
            pause(producer)
        raise ValueError("source observation stopped")

    def command(argv, cwd, environment, log, **limits):
        outer = signal.getsignal(signal.SIGTERM)
        code = ("import os,pathlib,sys,time; "
            "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()),encoding='ascii'); "
            "print('local dependency cancellation probe',flush=True); ")
        if boundary == "bounded":
            code += "pathlib.Path(sys.argv[2]).touch(); time.sleep(30)"
        result = run_bounded([sys.executable, "-I", "-B", "-c", code,
            str(directory / "child.pid"), str(directory / "ready")],
            workspace if boundary == "inert-verification" else cwd, environment, log,
            **dict(limits, min_free_bytes=1, max_rss_bytes=128 * 1024**2))
        observations.append({"result": result,
            "outer_handler_installed": callable(outer) and outer is not previous,
            "outer_handler_restored": signal.getsignal(signal.SIGTERM) is outer})
        if boundary == "unknown-child":
            pause(producers[0])
        return result

    def checkpoint(producer):
        if boundary == "prelaunch" and producer.report["commands"] and not paused:
            pause(producer)
        save(producer)

    def stability(producer, label):
        if boundary == "final-stability" and label == "final" and not paused:
            pause(producer)
        stable(producer, label)

    def record_inventory(producer):
        if boundary == "final-records" and not paused:
            pause(producer)
        records(producer)

    def retained_inventory(producer):
        if boundary == "final-retention" and not paused:
            pause(producer)
        return retained(producer)

    arguments = ["--workspace-dir", str(workspace), "--output-dir", str(output),
        "--preparation", str(directory / "preparation.json"), "--expected-revision", "1" * 40]
    with ExitStack() as completion, \
            mock.patch.object(build.Builder, "execute", new=executing), \
            mock.patch.object(build, "collect_source", side_effect=source), \
            mock.patch.object(build, "run_bounded", side_effect=command), \
            mock.patch.object(build.Builder, "save", new=checkpoint), \
            mock.patch.object(build.Builder, "stable", new=stability), \
            mock.patch.object(build.Builder, "_retain_record_inventory", new=record_inventory), \
            mock.patch.object(build.Builder, "retained_inventory", new=retained_inventory):
        if boundary == "inert-verification":
            import p06_dependency_receipt as receipt

            # Synthetic prerequisites reach receipt verification without building dependencies.
            (directory / "preparation.json").write_text('{"repositories": {}}')
            patches = (
                mock.patch.object(build.base, "_source_ok"),
                mock.patch.object(build, "helper_inventory", return_value=[]),
                mock.patch.object(build, "tool_inventory", return_value={
                    name: {"path": sys.executable} for name in build.HOST_TOOLS}),
                mock.patch.object(build.shutil, "disk_usage", return_value=SimpleNamespace(
                    free=contract.BUDGET["min_free_bytes"])),
                mock.patch.object(build, "available_memory_bytes", return_value=contract.BUDGET["max_rss_bytes"]),
                mock.patch.object(build.sources, "materialize_sources", return_value={"sources": []}),
                mock.patch.object(build.graph, "source_plan", return_value=[]),
                mock.patch.object(build.sources, "verify_sources", return_value=[]),
                mock.patch.object(build.Builder, "verify_products"),
                mock.patch.object(build.Builder, "retain_build_inputs"),
                mock.patch.object(build.Builder, "stage"),
                mock.patch.object(receipt, "validate_preparation", return_value=None),
                mock.patch.object(receipt, "load_receipt", side_effect=lambda *args, **kwargs: pause(producers[0])),
            )
            for patch in patches:
                completion.enter_context(patch)
        status = build.main(arguments)
    report = json.loads((output / "report.json").read_text())
    build.base._write_json(workspace / "evidence/qualified-warm-run.json", {
        "state": "finished", "stages": [{"id": "dependency-build",
            "report_path": "dependency-build/report.json", "process_started": True,
            "cleanup_complete": True}]})
    import p06_qualified_warm_hosted as hosted

    log = output / (report["commands"][0]["log"] if report["commands"] else "logs/local-child.log")
    result = {"main_status": status, "report": report, "observations": observations,
        "report_matches_memory": report == producers[0].report,
        "handler_restored": signal.getsignal(signal.SIGTERM) is previous,
        "sigint_unchanged": signal.getsignal(signal.SIGINT) is sigint,
        "writers_finished": hosted.writers_finished(directory, [{"id": "native-supervisor",
            "process_started": True, "cleanup_complete": True}]),
        "log": log.read_text() if log.exists() else None}
    (directory / "result.json").write_text(json.dumps(result))
    return status


@unittest.skipUnless(os.name == "posix" and Path("/proc/self/stat").exists(),
                     "dependency cancellation requires Linux /proc")
class DependencyCancellationTests(unittest.TestCase):
    def interrupted(self, boundary):
        with tempfile.TemporaryDirectory(prefix="p06-dependency-cancellation-") as temporary:
            directory = Path(temporary)
            code = ("import sys; sys.path.insert(0,sys.argv[1]); "
                "from test_p06_dependency_cancellation import _scenario; "
                "sys.exit(_scenario(sys.argv[2],sys.argv[3]))")
            process = subprocess.Popen([sys.executable, "-I", "-B", "-c", code,
                str(HERE), str(directory), boundary], cwd=HERE,
                env=dict(os.environ, TMPDIR=str(directory), PYTHONDONTWRITEBYTECODE="1"),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            try:
                deadline = time.monotonic() + 10
                while not (directory / "ready").exists():
                    if process.poll() is not None:
                        output = b"".join(process.communicate(timeout=1))
                        self.fail("scenario exited before readiness: " + output.decode("utf-8", "replace"))
                    self.assertLess(time.monotonic(), deadline, "cancellation readiness timeout")
                    time.sleep(0.01)
                marker = directory / "child.pid"
                child_pid = int(marker.read_text()) if marker.exists() else None
                if boundary not in ("source", "prelaunch", "bounded"):
                    self.assertIsNotNone(child_pid)
                    self.assertFalse(Path("/proc", str(child_pid)).exists(), "completed child was not reaped")
                if boundary != "bounded":
                    checkpoint = json.loads((directory / "checkpoint.json").read_text())
                    self.assertEqual(checkpoint["state"],
                        "finished" if boundary == "inert-verification" else "running")
                    if boundary == "inert-verification":
                        self.assertEqual(checkpoint["outcome"], "pass")
                        self.assertIs(checkpoint["fresh_dependency_build_passed"], True)
                process.send_signal(signal.SIGTERM)
                output = b"".join(process.communicate(timeout=10))
                self.assertEqual(process.returncode, 1, output.decode("utf-8", "replace"))
                if child_pid is not None:
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
                        os.killpg(int(marker.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        self.assertEqual(result["main_status"], 1)
        self.assertTrue(result["report_matches_memory"])
        self.assertTrue(result["handler_restored"])
        self.assertTrue(result["sigint_unchanged"])
        report = result["report"]
        self.assertEqual(report["state"], "finished")
        for name in ("fresh_dependency_build_passed", *contract.FALSE_CLAIMS):
            self.assertIs(report[name], False, name)
        if result["observations"]:
            self.assertEqual(len(result["observations"]), 5 if boundary == "inert-verification" else 1)
            for observation in result["observations"]:
                self.assertTrue(observation["outer_handler_installed"])
                self.assertTrue(observation["outer_handler_restored"])
                self.assertTrue(observation["result"]["process_started"])
                self.assertTrue(observation["result"]["cleanup_complete"])
            self.assertEqual(result["log"], CHILD_LOG)
        return result

    def test_sigterm_before_a_child_finishes_blocked_and_allows_closeout(self):
        result = self.interrupted("source")
        self.assertEqual(result["report"]["outcome"], "blocked")
        self.assertEqual(result["report"]["reason"], "interrupted")
        self.assertEqual(result["report"]["commands"], [])
        self.assertEqual(result["observations"], [])
        self.assertIsNone(result["log"])
        self.assertTrue(result["writers_finished"])

    def test_sigterm_before_launch_checkpoint_proves_child_unstarted(self):
        result = self.interrupted("prelaunch")
        self.assertEqual(result["report"]["outcome"], "blocked")
        command = result["report"]["commands"][0]
        self.assertIs(command["process_started"], False)
        self.assertIs(command["cleanup_complete"], True)
        self.assertEqual(command["reason"], "interrupted")
        self.assertEqual(result["observations"], [])
        self.assertIsNone(result["log"])
        self.assertTrue(result["writers_finished"])

    def test_sigterm_after_a_reaped_child_preserves_passed_command(self):
        result = self.interrupted("after-child")
        self.assertEqual(result["report"]["outcome"], "fail")
        self.assertEqual(result["report"]["reason"], "interrupted")
        command = result["report"]["commands"][0]
        for key, value in result["observations"][0]["result"].items():
            self.assertEqual(command[key], value)
        self.assertEqual(command["outcome"], "pass")
        self.assertEqual(command["exit_code"], 0)
        self.assertTrue(result["writers_finished"])

    def test_sigterm_before_monitor_return_preserves_unknown_disposition(self):
        result = self.interrupted("unknown-child")
        self.assertEqual(result["report"]["outcome"], "fail")
        command = result["report"]["commands"][0]
        self.assertIsNone(command["process_started"])
        self.assertNotIn("cleanup_complete", command)
        self.assertNotIn("exit_code", command)
        self.assertIn(command["log"], [row["path"] for row in result["report"]["retained_files"]])
        self.assertFalse(result["writers_finished"])

    def test_sigterm_inside_bounded_child_keeps_monitor_cleanup(self):
        result = self.interrupted("bounded")
        self.assertEqual(result["report"]["outcome"], "fail")
        command = result["report"]["commands"][0]
        self.assertEqual(command["reason"], "interrupted_signal_" + str(signal.SIGTERM))
        self.assertNotEqual(command["exit_code"], 0)
        self.assertIs(command["process_started"], True)
        self.assertIs(command["cleanup_complete"], True)
        self.assertTrue(result["writers_finished"])

    def test_first_sigterm_during_final_inventory_preserves_primary_failure(self):
        for boundary in ("final-stability", "final-records", "final-retention"):
            with self.subTest(boundary=boundary):
                result = self.interrupted(boundary)
                report = result["report"]
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(report["reason"], "source observation stopped")
                self.assertEqual(report["failures"], [
                    {"stage": "execution", "reason": "source observation stopped"},
                    {"stage": boundary, "reason": "interrupted"}])
                self.assertEqual(report["commands"][0]["outcome"], "pass")
                self.assertEqual(report["commands"][0]["exit_code"], 0)
                self.assertTrue(result["writers_finished"])

    def test_sigterm_during_inert_verification_revokes_provisional_pass(self):
        result = self.interrupted("inert-verification")
        report = result["report"]
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual(report["reason"], "interrupted")
        self.assertEqual(report["failures"], [{"stage": "inert-verification", "reason": "interrupted"}])
        self.assertEqual(len(report["commands"]), 5)
        self.assertTrue(all(row["outcome"] == "pass" and row["exit_code"] == 0 for row in report["commands"]))
        self.assertTrue(result["writers_finished"])

    def test_cli_restores_enclosing_handler_on_parser_unwind(self):
        def enclosing(number, frame):
            raise AssertionError("enclosing handler must not run")

        previous = signal.signal(signal.SIGTERM, enclosing)
        sigint = signal.getsignal(signal.SIGINT)
        parse_args = build.argparse.ArgumentParser.parse_args
        observations = []

        def parse(parser, *args, **kwargs):
            current = signal.getsignal(signal.SIGTERM)
            observations.append(callable(current) and current is not enclosing)
            return parse_args(parser, *args, **kwargs)

        try:
            for arguments, code in ((["--help"], 0), ([], 2)):
                with self.subTest(arguments=arguments), redirect_stdout(io.StringIO()), \
                        redirect_stderr(io.StringIO()), \
                        mock.patch.object(build.argparse.ArgumentParser, "parse_args", new=parse), \
                        self.assertRaises(SystemExit) as raised:
                    build.main(arguments)
                self.assertEqual(raised.exception.code, code)
                self.assertIs(signal.getsignal(signal.SIGTERM), enclosing)
                self.assertIs(signal.getsignal(signal.SIGINT), sigint)
            self.assertEqual(observations, [True, True])
        finally:
            signal.signal(signal.SIGTERM, previous)

    def test_direct_builder_keeps_worker_thread_execution(self):
        with tempfile.TemporaryDirectory(prefix="p06-dependency-thread-") as temporary:
            workspace = Path(temporary)
            producer = build.Builder(SimpleNamespace(source_dir=build.ROOT,
                workspace_dir=workspace, output_dir=workspace / "evidence", expected_revision="invalid"))
            results, errors = [], []

            def execute():
                try:
                    results.append(producer.execute())
                except BaseException as error:
                    errors.append(error)

            thread = threading.Thread(target=execute)
            thread.start()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["state"], "finished")
            self.assertEqual(results[0]["outcome"], "blocked")
            self.assertEqual(results[0]["reason"], "exact expected revision required")


if __name__ == "__main__":
    unittest.main()
