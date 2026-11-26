# SPDX-License-Identifier: Apache-2.0
"""CLI termination retains only bounded synthetic private control bytes."""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

import p06_qualified_warm_control as control
from test_p06_qualified_warm_control import AZURE, BODY, Response


PUBLIC_FIELDS = {"contract_id", "outcome", "reason_code", "reason",
                 "original_verified", "native_execution"}
EXPECTED = {"sha256": hashlib.sha256(BODY).hexdigest(), "size_bytes": len(BODY)}


@contextmanager
def _fixture():
    with mock.patch.object(control, "_reviewed_identity", return_value=EXPECTED) as proof, \
            mock.patch.object(control.os, "fstatvfs", return_value=
                              SimpleNamespace(f_bavail=100 * 1024**3, f_frsize=1)), \
            mock.patch.dict(os.environ, {control.URL_ENVIRONMENT_VARIABLE: AZURE}):
        yield proof


def _signal_child(boundary, observation, output):
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    previous = signal.getsignal(signal.SIGTERM)
    sigint = signal.getsignal(signal.SIGINT)

    def alarm(number, frame):
        raise AssertionError("enclosing alarm handler must not run")

    signal.signal(signal.SIGALRM, alarm)
    descriptors, signals = [], []

    class Output(control._PrivateOutput):
        def __init__(self, value):
            super().__init__(value)
            descriptors.append(self.descriptor)

        def create(self, name):
            descriptor = super().create(name)
            descriptors.append(descriptor)
            return descriptor

    def interrupt():
        signals.append(signal.SIGTERM)
        os.kill(os.getpid(), signal.SIGTERM)
        raise AssertionError("SIGTERM did not interrupt private intake")

    def read(response):
        if response.position:
            interrupt()

    response = Response(read_hook=read)
    connection = mock.Mock()
    connection.getresponse.return_value = response
    with _fixture() as proof, \
            mock.patch.object(control, "_PrivateOutput", Output), \
            mock.patch.object(control.http.client, "HTTPSConnection", return_value=connection), \
            mock.patch("subprocess.Popen", side_effect=AssertionError("no subprocess")):
        if boundary == "preflight":
            proof.side_effect = interrupt
        status = control.main(["--output-dir", output])
        consumed = control.URL_ENVIRONMENT_VARIABLE not in os.environ

    closed = []
    for descriptor in descriptors:
        try:
            os.fstat(descriptor)
        except OSError as error:
            closed.append(error.errno == errno.EBADF)
        else:
            closed.append(False)
    Path(observation).write_text(json.dumps({
        "signals": signals, "environment_consumed": consumed,
        "response_closed": response.closed,
        "connection_close_calls": connection.close.call_count,
        "request_calls": connection.request.call_count,
        "descriptors_closed": closed,
        "sigterm_restored": signal.getsignal(signal.SIGTERM) is previous,
        "sigint_unchanged": signal.getsignal(signal.SIGINT) is sigint,
        "sigalrm_restored": signal.getsignal(signal.SIGALRM) is alarm,
        "deadline_cleared": signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0),
    }))
    return status


class ControlSigtermCloseoutTests(unittest.TestCase):
    def assert_no_claims(self, report):
        self.assertFalse(report["original_verified"])
        self.assertEqual(report["native_execution"], "not_run")
        for name in (*control.dependency.FALSE_CLAIMS, "retained_code_executed",
                     "archive_extracted", "archive_repacked", "counter_qualification_passed",
                     "qualified_warm_passed"):
            self.assertIs(report[name], False)

    def check_signal(self, boundary):
        with tempfile.TemporaryDirectory(prefix="p06-control-sigterm-") as temporary:
            root = Path(temporary).resolve()
            output, observation = root / "intake", root / "observation.json"
            script = ("import sys, test_p06_control_sigterm_closeout as t; "
                      "sys.exit(t._signal_child(*sys.argv[1:]))")
            result = subprocess.run([sys.executable, "-B", "-c", script, boundary,
                                     str(observation), str(output)],
                                    cwd=Path(control.__file__).resolve().parent,
                                    env={"TMPDIR": str(root), "PYTHONDONTWRITEBYTECODE": "1"},
                                    capture_output=True, text=True, timeout=8)
            self.assertEqual(result.returncode, 1,
                             "default SIGTERM exit bypassed private intake closeout")
            self.assertEqual(result.stderr, "")
            self.assertEqual(len(result.stdout.splitlines()), 1)
            summary = json.loads(result.stdout)
            self.assertEqual(set(summary), PUBLIC_FIELDS)
            receipt_text = (output / control.RECEIPT_NAME).read_text()
            report = json.loads(receipt_text)
            self.assertEqual(summary, {key: report[key] for key in PUBLIC_FIELDS})
            self.assertEqual(report["outcome"], "fail" if boundary == "transfer" else "blocked")
            self.assertEqual(report["reason_code"], "interrupted")
            self.assertEqual(report["reason"], control._REASONS["interrupted"])
            self.assertEqual(report["state"], "finished")
            self.assert_no_claims(report)
            for secret in (AZURE, str(root), "never-retain", "https:", "sig=", "fixtureaccount"):
                self.assertNotIn(secret, result.stdout + result.stderr + receipt_text)
            observed = json.loads(observation.read_text())
            self.assertEqual(observed["signals"], [signal.SIGTERM])
            for key in ("environment_consumed", "sigterm_restored", "sigint_unchanged",
                        "sigalrm_restored", "deadline_cleared"):
                self.assertTrue(observed[key], key)
            self.assertTrue(observed["descriptors_closed"])
            self.assertTrue(all(observed["descriptors_closed"]))
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((output / control.RECEIPT_NAME).stat().st_mode), 0o600)
            archive = output / control.ARCHIVE_NAME
            if boundary == "transfer":
                self.assertTrue(report["network_acquisition"])
                self.assertTrue(observed["response_closed"])
                self.assertEqual(observed["connection_close_calls"], 1)
                self.assertEqual(observed["request_calls"], 1)
                self.assertEqual(archive.read_bytes(), BODY[:7])
                self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o600)
                self.assertEqual(report["retained_state"], "partial")
                self.assertEqual(report["retained_original"], {
                    "path": control.ARCHIVE_NAME, "size_bytes": 7,
                    "sha256": hashlib.sha256(BODY[:7]).hexdigest()})
            else:
                self.assertFalse(report["network_acquisition"])
                self.assertFalse(observed["response_closed"])
                self.assertEqual(observed["connection_close_calls"], 0)
                self.assertEqual(observed["request_calls"], 0)
                self.assertFalse(archive.exists())
                self.assertEqual(report["retained_state"], "absent")
                self.assertIsNone(report["retained_original"])

    def test_sigterm_during_transfer_retains_partial_bytes_and_closes_resources(self):
        self.check_signal("transfer")

    def test_sigterm_before_transfer_retains_sanitized_blocked_receipt(self):
        self.check_signal("preflight")

    def test_cli_restores_enclosing_handlers_on_success_error_and_system_exit(self):
        def enclosing(number, frame):
            raise AssertionError("enclosing handler must not run inside the CLI")

        previous = signal.signal(signal.SIGTERM, enclosing)
        other_handlers = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGALRM)}
        try:
            for error in (None, control.IntakeError("invalid_arguments"),
                          KeyboardInterrupt("never-retain-this-secret"), SystemExit(23)):
                with self.subTest(error=type(error).__name__):
                    seen = []

                    def parse(argv):
                        seen.append(signal.getsignal(signal.SIGTERM))
                        if error is not None:
                            raise error
                        return SimpleNamespace(output_dir="/unused")

                    parser = mock.Mock()
                    parser.parse_args.side_effect = parse
                    report = {"contract_id": control.CONTRACT_ID, "outcome": "pass",
                              "reason_code": None, "reason": None, "original_verified": True,
                              "native_execution": "not_run"}
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with mock.patch.object(control, "argument_parser", return_value=parser), \
                            mock.patch.object(control, "acquire_control", return_value=report), \
                            redirect_stdout(stdout), redirect_stderr(stderr):
                        if isinstance(error, SystemExit):
                            with self.assertRaises(SystemExit) as caught:
                                control.main([])
                            self.assertIs(caught.exception, error)
                        else:
                            self.assertEqual(control.main([]), int(error is not None))
                    self.assertEqual(len(seen), 1)
                    self.assertTrue(callable(seen[0]))
                    self.assertIsNot(seen[0], enclosing)
                    self.assertIs(signal.getsignal(signal.SIGTERM), enclosing)
                    for number, handler in other_handlers.items():
                        self.assertIs(signal.getsignal(number), handler)
                    self.assertEqual(stderr.getvalue(), "")
                    self.assertNotIn("never-retain", stdout.getvalue())
        finally:
            signal.signal(signal.SIGTERM, previous)

    def test_direct_worker_api_preserves_main_thread_deadline_requirement(self):
        with tempfile.TemporaryDirectory(prefix="p06-control-worker-") as temporary, _fixture():
            output = Path(temporary).resolve() / "intake"
            reports, failures = [], []
            opener = mock.Mock(side_effect=AssertionError("no transfer in worker thread"))

            def acquire():
                try:
                    reports.append(control.acquire_control(output, opener=opener))
                except BaseException as error:
                    failures.append(error)

            handlers = {number: signal.getsignal(number)
                        for number in (signal.SIGTERM, signal.SIGINT, signal.SIGALRM)}
            with mock.patch.object(control.signal, "signal",
                                   side_effect=AssertionError("signal mutation")) as install:
                worker = threading.Thread(target=acquire, daemon=True)
                worker.start()
                worker.join(timeout=3)
                self.assertFalse(worker.is_alive())
                install.assert_not_called()
            self.assertEqual(failures, [])
            self.assertEqual(len(reports), 1)
            report = reports[0]
            self.assertEqual(report["outcome"], "blocked")
            self.assertEqual(report["reason_code"], "timeout_unavailable")
            self.assert_no_claims(report)
            self.assertEqual(report, json.loads((output / control.RECEIPT_NAME).read_text()))
            self.assertEqual((output / control.ARCHIVE_NAME).read_bytes(), b"")
            opener.assert_not_called()
            for number, handler in handlers.items():
                self.assertIs(signal.getsignal(number), handler)


if __name__ == "__main__":
    unittest.main()
