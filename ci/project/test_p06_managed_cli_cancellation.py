# SPDX-License-Identifier: Apache-2.0
"""Managed CLI SIGTERM boundaries; host fixtures provide no native evidence."""

from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
import importlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
ENTRIES = (
    ("p06_managed_preflight_execute", "native_preflight_passed"),
    ("p06_native_lifetime_execute", "native_lifetime_passed"),
    ("p06_dependency_lifetime_execute", "dependency_source_to_loaded_binary_verified"),
    ("p06_counter_qualification_execute", "counter_qualification_passed"),
)


def _arguments(args):
    return ["run", *(item for name, value in vars(args).items()
        if name not in ("mode", "verilator") and value is not None
        for item in ("--" + name.replace("_", "-"), str(value)))]


def _scenario(directory, boundary):
    from test_p06_managed_preflight_runner import ManagedHarness
    import p06_managed_preflight_execute as runner

    directory = Path(directory)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    previous = signal.getsignal(signal.SIGTERM)
    sigint = signal.getsignal(signal.SIGINT)
    temporary_directory = tempfile.TemporaryDirectory

    def confined_temporary_directory(*args, **kwargs):
        return temporary_directory(*args, **dict(kwargs, dir=directory))

    with ExitStack() as stack:
        with mock.patch.object(tempfile, "TemporaryDirectory", side_effect=confined_temporary_directory):
            fixture = stack.enter_context(ManagedHarness())
        fixture_root = fixture.paths["source"].parent
        assert fixture_root.is_relative_to(directory)
        receipt = fixture.paths["output"] / "report.json"
        write = runner.base._write_json
        paused = False

        def pause(report):
            nonlocal paused
            paused = True
            (directory / "checkpoint.json").write_bytes(receipt.read_bytes())
            (directory / "boundary.json").write_text(json.dumps({
                "fixture_root": str(fixture_root),
                "report": report,
                "calls": [row["id"] for row in fixture.calls],
                "handler_installed": callable(signal.getsignal(signal.SIGTERM)),
            }), encoding="utf-8")
            (directory / "ready").touch()
            signal.pause()
            raise AssertionError("SIGTERM did not interrupt the selected checkpoint")

        def checkpoint(path, report):
            if Path(path) == receipt and not paused and report["state"] == "running":
                if boundary == "initial" and not report["commands"]:
                    write(path, report)
                    pause(report)
                elif (boundary == "receipt" and report["commands"]
                        and report["commands"][-1]["native_process"]
                        and report["commands"][-1]["process_started"] is True):
                    pause(report)
            return write(path, report)

        with mock.patch.object(runner.base, "resolve_paths", return_value=fixture.paths), \
                mock.patch.object(runner.base, "_write_json", side_effect=checkpoint):
            status = runner.main(_arguments(fixture.args))
        report = json.loads(receipt.read_text())
        (directory / "result.json").write_text(json.dumps({
            "main_status": status, "report": report,
            "calls": [row["id"] for row in fixture.calls],
            "launches": fixture.launches(),
            "handler_restored": signal.getsignal(signal.SIGTERM) is previous,
            "sigint_unchanged": signal.getsignal(signal.SIGINT) is sigint,
        }), encoding="utf-8")
    assert not fixture_root.exists()
    return status


@contextmanager
def _enclosing_handlers():
    install = signal.signal
    previous = signal.getsignal(signal.SIGTERM)
    sigint = signal.getsignal(signal.SIGINT)

    def enclosing(number, frame):
        raise AssertionError("CLI must translate SIGTERM before entering its body")

    install(signal.SIGTERM, enclosing)
    try:
        yield enclosing, sigint
    finally:
        install(signal.SIGTERM, previous)
        install(signal.SIGINT, sigint)


class ManagedCliCancellationTests(unittest.TestCase):
    def interrupted(self, boundary):
        with tempfile.TemporaryDirectory(prefix="p06-managed-cli-cancellation-") as temporary:
            directory = Path(temporary).resolve()
            code = ("import sys; from test_p06_managed_cli_cancellation import _scenario; "
                    "sys.exit(_scenario(sys.argv[1],sys.argv[2]))")
            process = subprocess.Popen([sys.executable, "-B", "-c", code, str(directory), boundary],
                cwd=HERE, env=dict(os.environ, TMPDIR=str(directory), PYTHONDONTWRITEBYTECODE="1"),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            try:
                deadline = time.monotonic() + 10
                while not (directory / "ready").exists():
                    if process.poll() is not None:
                        output = b"".join(process.communicate(timeout=1))
                        self.fail("scenario exited before checkpoint: " + output.decode("utf-8", "replace"))
                    self.assertLess(time.monotonic(), deadline, "checkpoint readiness timeout")
                    time.sleep(0.01)
                saved = json.loads((directory / "checkpoint.json").read_text())
                observed = json.loads((directory / "boundary.json").read_text())
                fixture_root = Path(observed["fixture_root"])
                self.assertTrue(fixture_root.is_relative_to(directory))
                self.assertEqual(saved["state"], "running")
                if boundary == "initial":
                    self.assertEqual(saved["native_execution"], "not_run")
                    self.assertEqual(saved["commands"], [])
                else:
                    self.assertEqual(saved["native_execution"], "unknown")
                    self.assertIsNone(saved["commands"][-1]["process_started"])
                    self.assertEqual(observed["report"]["native_execution"], "run")
                    self.assertIs(observed["report"]["commands"][-1]["process_started"], True)
                process.send_signal(signal.SIGTERM)
                output = b"".join(process.communicate(timeout=10))
                self.assertEqual(process.returncode, 1,
                    "checkpoint=" + boundary + "; saved=" + json.dumps({
                        "state": saved["state"], "native_execution": saved["native_execution"],
                        "commands": len(saved["commands"]),
                    }) + "; output=" + output.decode("utf-8", "replace"))
                result = json.loads((directory / "result.json").read_text())
                self.assertFalse(fixture_root.exists(), "completed scenario did not clean its fixture")
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
                for stream in (process.stdout, process.stderr):
                    stream.close()
        self.assertFalse(directory.exists(), "parent did not clean the scenario directory")
        self.assertTrue(observed["handler_installed"])
        self.assertEqual(result["main_status"], 1)
        self.assertTrue(result["handler_restored"])
        self.assertTrue(result["sigint_unchanged"])
        self.assertEqual(result["calls"], observed["calls"], "commands continued after cancellation")
        report = result["report"]
        self.assertEqual(report["state"], "finished")
        self.assertEqual(report["reason"], "interrupted")
        self.assertEqual(report["failures"][0]["stage"], "execution")
        self.assertEqual(report["failures"][0]["reason"], "interrupted")
        self.assertFalse(any(report["completed_counts"].values()))
        self.assertTrue(report["retained_files_stable"])
        runner = importlib.import_module(ENTRIES[0][0])
        for field in ("native_preflight_passed", *runner.manifest.FALSE_CLAIMS):
            self.assertIs(report[field], False, field)
        return result, observed

    def test_sigterm_after_initial_checkpoint_finishes_without_dispatch(self):
        result, _ = self.interrupted("initial")
        report = result["report"]
        self.assertEqual(report["outcome"], "blocked")
        self.assertEqual(report["native_execution"], "not_run")
        self.assertEqual(report["commands"], [])
        self.assertEqual(report["processes"], [])
        self.assertEqual(report["raw_logs"], [])
        self.assertEqual(result["calls"], [])
        self.assertEqual(result["launches"], [])

    def test_sigterm_before_native_receipt_write_keeps_confirmed_start(self):
        from test_p06_managed_preflight_runner import FIRST

        result, observed = self.interrupted("receipt")
        report = result["report"]
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual(report["native_execution"], "run")
        self.assertEqual(result["launches"], [FIRST])
        self.assertEqual(len(report["processes"]), 1)
        self.assertEqual(report["processes"][0]["outcome"], "fail")
        command = report["commands"][-1]
        self.assertEqual(command, observed["report"]["commands"][-1])
        self.assertEqual(command["id"], FIRST)
        self.assertIs(command["process_started"], True)
        self.assertIs(command["cleanup_complete"], True)
        self.assertEqual(command["exit_code"], 0)
        self.assertEqual(command["outcome"], "pass")
        self.assertEqual(len(report["raw_logs"]), len(report["commands"]))
        self.assertIn({"path": command["log"], "sha256": command["log_sha256"],
            "size_bytes": command["log_size_bytes"]}, report["raw_logs"])

    def assert_handlers_restored(self, handlers):
        enclosing, sigint = handlers
        self.assertIs(signal.getsignal(signal.SIGTERM), enclosing)
        self.assertIs(signal.getsignal(signal.SIGINT), sigint)

    def test_all_cli_entries_translate_sigterm_before_argument_parsing(self):
        for name, _ in ENTRIES:
            module = importlib.import_module(name)
            with self.subTest(entry=name), _enclosing_handlers() as handlers:
                def parser():
                    self.assertIsNot(signal.getsignal(signal.SIGTERM), handlers[0])
                    self.assertIs(signal.getsignal(signal.SIGINT), handlers[1])
                    os.kill(os.getpid(), signal.SIGTERM)
                    self.fail("SIGTERM did not interrupt argument parsing")

                with mock.patch.object(module, "argument_parser", side_effect=parser), \
                        mock.patch.object(module, "execute") as execute:
                    with self.assertRaises(KeyboardInterrupt):
                        module.main([])
                execute.assert_not_called()
                self.assert_handlers_restored(handlers)

    def test_all_cli_argv_and_success_or_failure_exit_statuses_are_preserved(self):
        for name, field in ENTRIES:
            module = importlib.import_module(name)
            base = module.base if name == ENTRIES[0][0] else module.preflight.base
            for passed in (False, True):
                for argv in (None, ["literal", "--preserved-argv"]):
                    with self.subTest(entry=name, passed=passed, argv=argv), _enclosing_handlers() as handlers:
                        args = mock.Mock(output="/managed-cli-output")
                        paths = object()
                        result = {"outcome": "pass" if passed else "fail", "reason": None,
                            "completed_counts": {}, **dict.fromkeys((item[1] for item in ENTRIES), passed)}
                        output = io.StringIO()
                        with mock.patch.object(module, "argument_parser") as parser, \
                                mock.patch.object(base, "resolve_paths", return_value=paths) as resolve, \
                                mock.patch.object(module, "execute", return_value=result) as execute, \
                                redirect_stdout(output):
                            parser.return_value.parse_args.return_value = args
                            status = module.main(argv)
                        parser.return_value.parse_args.assert_called_once_with(argv)
                        self.assertIs(parser.return_value.parse_args.call_args.args[0], argv)
                        resolve.assert_called_once_with(args)
                        execute.assert_called_once_with(args, paths)
                        self.assertEqual(status, 0 if passed else 1)
                        self.assertEqual(json.loads(output.getvalue())[field], passed)
                        self.assert_handlers_restored(handlers)

    def test_all_cli_handled_errors_keep_blocked_json_and_restore_handler(self):
        for name, field in ENTRIES:
            module = importlib.import_module(name)
            base = module.base if name == ENTRIES[0][0] else module.preflight.base
            errors = (OSError, ValueError, RuntimeError)
            if name != ENTRIES[0][0]:
                errors += (ImportError, TypeError)
            for error_type in errors:
                with self.subTest(entry=name, error=error_type.__name__), _enclosing_handlers() as handlers:
                    error = error_type("original failure")
                    output = io.StringIO()
                    with mock.patch.object(module, "argument_parser"), \
                            mock.patch.object(base, "resolve_paths", side_effect=error), \
                            mock.patch.object(module, "execute") as execute, redirect_stdout(output):
                        self.assertEqual(module.main([]), 1)
                    execute.assert_not_called()
                    summary = json.loads(output.getvalue())
                    self.assertEqual(summary["outcome"], "blocked")
                    self.assertEqual(summary["reason"], str(error))
                    self.assertIs(summary[field], False)
                    self.assert_handlers_restored(handlers)

    def test_all_cli_unhandled_error_identity_and_handler_restoration(self):
        for name, _ in ENTRIES:
            module = importlib.import_module(name)
            with self.subTest(entry=name), _enclosing_handlers() as handlers:
                error = LookupError("original unhandled failure")
                with mock.patch.object(module, "argument_parser", side_effect=error):
                    with self.assertRaises(LookupError) as caught:
                        module.main([])
                self.assertIs(caught.exception, error)
                self.assert_handlers_restored(handlers)

    def test_all_cli_parser_exit_codes_restore_handler(self):
        for name, _ in ENTRIES:
            module = importlib.import_module(name)
            for argv, status in ((["--help"], 0), ([], 2)):
                with self.subTest(entry=name, argv=argv), _enclosing_handlers() as handlers:
                    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
                            self.assertRaises(SystemExit) as caught:
                        module.main(argv)
                    self.assertEqual(caught.exception.code, status)
                    self.assert_handlers_restored(handlers)

    def test_all_cli_sigterm_during_installation_restores_handler(self):
        for name, _ in ENTRIES:
            module = importlib.import_module(name)
            with self.subTest(entry=name), _enclosing_handlers() as handlers:
                install = signal.signal
                injections = []

                def interrupted_install(number, handler):
                    prior = install(number, handler)
                    if not injections:
                        injections.append(number)
                        os.kill(os.getpid(), signal.SIGTERM)
                    return prior

                with mock.patch.object(signal, "signal", side_effect=interrupted_install), \
                        mock.patch.object(module, "argument_parser", side_effect=AssertionError("body entered")) as parser:
                    with self.assertRaises(KeyboardInterrupt):
                        module.main([])
                parser.assert_not_called()
                self.assertEqual(injections, [signal.SIGTERM])
                self.assert_handlers_restored(handlers)

    def test_all_cli_signal_setup_error_preserves_identity_and_restores_handler(self):
        for name, _ in ENTRIES:
            module = importlib.import_module(name)
            with self.subTest(entry=name), _enclosing_handlers() as handlers:
                install = signal.signal
                error = RuntimeError("signal installation failed after installing")
                calls = []

                def failed_install(number, handler):
                    prior = install(number, handler)
                    calls.append((number, handler))
                    if len(calls) == 1:
                        raise error
                    return prior

                with mock.patch.object(signal, "signal", side_effect=failed_install), \
                        mock.patch.object(module, "argument_parser", side_effect=AssertionError("body entered")) as parser:
                    with self.assertRaises(RuntimeError) as caught:
                        module.main([])
                self.assertIs(caught.exception, error)
                parser.assert_not_called()
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[-1], (signal.SIGTERM, handlers[0]))
                self.assert_handlers_restored(handlers)


if __name__ == "__main__":
    unittest.main()
