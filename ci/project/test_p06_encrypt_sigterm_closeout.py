# SPDX-License-Identifier: Apache-2.0
"""Cooperative CLI termination with bounded synthetic age processes only."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

import p06_qualified_warm_encrypt as encrypt
from test_p06_encrypt_operational_failures import encryption_fixture
from test_p06_qualified_warm_encrypt import PUBLIC_FIELDS, RECIPIENT, REVISION


def _arguments(fixture):
    return ["--input-dir", str(fixture.source), "--output-dir", str(fixture.output),
            "--recipient", RECIPIENT, "--age-binary", str(fixture.binary),
            "--expected-revision", REVISION]


def _publication_child(boundary, observation, argv):
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    previous = signal.getsignal(signal.SIGTERM)
    args = encrypt.argument_parser().parse_args(argv)
    output = Path(args.output_dir)
    private = Path(str(output) + encrypt.PRIVATE_SUFFIX)
    original_link, original_unlink = os.link, os.unlink
    observed = {}

    def interrupt():
        ciphertext = output / encrypt.CIPHERTEXT_NAME
        body = ciphertext.read_bytes()
        observed.update(ciphertext_sha256=hashlib.sha256(body).hexdigest(),
                        ciphertext_bytes=len(body),
                        private_cipher_exists=(private / encrypt.INCOMPLETE_NAME).exists(),
                        private_summary_exists=(private / encrypt.PRIVATE_SUMMARY_NAME).exists())
        Path(observation).write_text(json.dumps(observed))
        os.kill(os.getpid(), signal.SIGTERM)
        raise AssertionError("SIGTERM did not interrupt encryption publication")

    def link(source, target, **kwargs):
        result = original_link(source, target, **kwargs)
        if not observed and boundary == "link-" + target:
            interrupt()
        return result

    def unlink(name, **kwargs):
        result = original_unlink(name, **kwargs)
        if not observed and boundary == "unlink-" + name:
            interrupt()
        return result

    with mock.patch.object(encrypt.os, "link", side_effect=link), \
            mock.patch.object(encrypt.os, "unlink", side_effect=unlink):
        status = encrypt.main(argv)
    observed["handler_restored"] = signal.getsignal(signal.SIGTERM) is previous
    Path(observation).write_text(json.dumps(observed))
    return status


class EncryptionSigtermCloseoutTests(unittest.TestCase):
    def _not_running(self, pid):
        try:
            return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].split()[0] == "Z"
        except FileNotFoundError:
            return True

    def _wait_until(self, condition, message, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(0.01)
        self.fail(message)

    def _assert_sanitized_failure(self, fixture, stdout, stderr):
        self.assertEqual(stderr, "")
        self.assertEqual(len(stdout.splitlines()), 1)
        summary = json.loads(stdout)
        self.assertEqual(set(summary), PUBLIC_FIELDS)
        self.assertFalse(summary["encryption_passed"])
        self.assertEqual(summary["outcome"], "fail")
        self.assertEqual(summary["expected_revision"], REVISION)
        self.assertEqual(summary["ciphertext_bytes"], 0)
        self.assertIsNone(summary["ciphertext_sha256"])
        for secret in (str(fixture.root), RECIPIENT, "PRIVATE-STDERR-SECRET", "PRIVATE_TOKEN",
                       fixture.secret.decode("latin1")):
            self.assertNotIn(secret, stdout)

    def _assert_diagnostic(self, fixture, *, committed, stage):
        diagnostic = json.loads((fixture.private / encrypt.DIAGNOSTIC_NAME).read_bytes())
        self.assertEqual(diagnostic["error_type"], "KeyboardInterrupt")
        self.assertEqual(diagnostic["stage"], stage)
        self.assertEqual(diagnostic["publication_committed"], committed)
        self.assertTrue(diagnostic["cleanup_complete"])
        self.assertFalse(diagnostic["encryption_passed"])
        self.assertFalse(diagnostic["plaintext_publication_authorized"])

    def test_direct_cli_sigterm_stops_age_group_and_retains_partial_ciphertext(self):
        with encryption_fixture() as fixture:
            source_before = fixture.source_bytes()
            partial = b"age-encryption.org/v1\nSYNTHETIC-PARTIAL-CIPHERTEXT\n"
            private_stderr = b"PRIVATE-STDERR-SECRET ?token=PRIVATE_TOKEN\n"
            fixture.binary.write_text(f'''#!{sys.executable}
import json, os, pathlib, signal, subprocess, sys, time
child = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(15)"])
def terminate(number, frame):
    child.wait(timeout=2)
    sys.exit(0)
signal.signal(signal.SIGTERM, terminate)
pathlib.Path({str(fixture.audit)!r}).write_text(json.dumps({{"pid": os.getpid(), "child_pid": child.pid}}))
os.write(1, {partial!r})
os.write(2, {private_stderr!r})
time.sleep(15)
child.wait(timeout=2)
''')
            process = subprocess.Popen([sys.executable, "-B", str(Path(encrypt.__file__).resolve()),
                                        *_arguments(fixture)], stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, start_new_session=True)
            record = None
            try:
                def ready():
                    nonlocal record
                    if process.poll() is not None:
                        self.fail("encryption CLI exited before the signal boundary")
                    cipher = fixture.private / encrypt.INCOMPLETE_NAME
                    stderr = fixture.private / encrypt.STDERR_NAME
                    if (cipher.exists() and cipher.read_bytes() == partial and stderr.exists()
                            and stderr.read_bytes() == private_stderr):
                        record = json.loads(fixture.audit.read_bytes())
                        return True
                    return False

                self._wait_until(ready, "synthetic age did not reach its bounded signal boundary")
                self.assertEqual(os.getpgid(record["pid"]), record["pid"])
                self.assertNotEqual(os.getpgid(record["pid"]), os.getpgid(process.pid))
                process.send_signal(signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 1,
                                 "default SIGTERM exit bypassed encryption closeout")
                self._assert_sanitized_failure(fixture, stdout, stderr)
                self._wait_until(lambda: all(self._not_running(pid) for pid in record.values()),
                                 "synthetic age process group remained live")
                fixture.assert_failed_public()
                self._assert_diagnostic(fixture, committed=False, stage="encryption")
                self.assertEqual((fixture.private / encrypt.INCOMPLETE_NAME).read_bytes(), partial)
                self.assertEqual((fixture.private / encrypt.STDERR_NAME).read_bytes(), private_stderr)
                self.assertEqual(fixture.source_bytes(), source_before)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)
                if record is None and fixture.audit.exists():
                    record = json.loads(fixture.audit.read_bytes())
                if record is not None:
                    for sig in (signal.SIGTERM, signal.SIGKILL):
                        if all(self._not_running(pid) for pid in record.values()):
                            break
                        try:
                            os.killpg(record["pid"], sig)
                        except ProcessLookupError:
                            pass
                        deadline = time.monotonic() + 3
                        while time.monotonic() < deadline:
                            if all(self._not_running(pid) for pid in record.values()):
                                break
                            time.sleep(0.01)

    def _check_publication_boundary(self, boundary, *, committed):
        with encryption_fixture() as fixture:
            source_before = fixture.source_bytes()
            observation = fixture.root / "boundary.PRIVATE.json"
            script = ("import sys, test_p06_encrypt_sigterm_closeout as t; "
                      "sys.exit(t._publication_child(sys.argv[1], sys.argv[2], sys.argv[3:]))")
            result = subprocess.run([sys.executable, "-B", "-c", script, boundary,
                                     str(observation), *_arguments(fixture)],
                                    cwd=Path(encrypt.__file__).resolve().parent,
                                    capture_output=True, text=True, timeout=8)
            self.assertEqual(result.returncode, 1,
                             "default SIGTERM exit bypassed publication closeout")
            self._assert_sanitized_failure(fixture, result.stdout, result.stderr)
            observed = json.loads(observation.read_bytes())
            self.assertTrue(observed["handler_restored"])
            self._assert_diagnostic(fixture, committed=committed,
                                    stage="private-cleanup" if committed else "publication")
            self.assertEqual(fixture.source_bytes(), source_before)
            if committed:
                self.assertFalse(observed["private_cipher_exists"])
                self.assertFalse((fixture.private / encrypt.INCOMPLETE_NAME).exists())
                ciphertext = (fixture.output / encrypt.CIPHERTEXT_NAME).read_bytes()
                summary = json.loads((fixture.output / encrypt.SUMMARY_NAME).read_bytes())
                self.assertTrue(summary["encryption_passed"])
                self.assertEqual(summary["ciphertext_sha256"], observed["ciphertext_sha256"])
                self.assertEqual(summary["ciphertext_bytes"], observed["ciphertext_bytes"])
                self.assertEqual((fixture.private / encrypt.PRIVATE_SUMMARY_NAME).exists(),
                                 boundary == "unlink-" + encrypt.INCOMPLETE_NAME)
            else:
                fixture.assert_failed_public()
                self.assertTrue(observed["private_cipher_exists"])
                ciphertext = (fixture.private / encrypt.INCOMPLETE_NAME).read_bytes()
                self.assertTrue((fixture.private / encrypt.PRIVATE_SUMMARY_NAME).exists())
            self.assertEqual(hashlib.sha256(ciphertext).hexdigest(), observed["ciphertext_sha256"])
            self.assertEqual(len(ciphertext), observed["ciphertext_bytes"])

    def test_sigterm_after_first_public_link_retains_private_last_copy(self):
        self._check_publication_boundary("link-" + encrypt.CIPHERTEXT_NAME, committed=False)

    def test_sigterm_after_public_summary_link_revokes_uncommitted_pass(self):
        self._check_publication_boundary("link-" + encrypt.SUMMARY_NAME, committed=False)

    def test_sigterm_after_private_cipher_unlink_preserves_committed_last_copy(self):
        self._check_publication_boundary("unlink-" + encrypt.INCOMPLETE_NAME, committed=True)

    def test_sigterm_after_private_summary_unlink_preserves_committed_pair(self):
        self._check_publication_boundary("unlink-" + encrypt.PRIVATE_SUMMARY_NAME, committed=True)

    def test_cli_handler_is_scoped_through_parse_success_failure_and_system_exit(self):
        def enclosing(number, frame):
            raise AssertionError("enclosing handler must not run inside the CLI")

        previous = signal.signal(signal.SIGTERM, enclosing)
        sigint = signal.getsignal(signal.SIGINT)
        try:
            for error in (None, encrypt.EncryptionError("PRIVATE_TOKEN"),
                          KeyboardInterrupt("PRIVATE_TOKEN"), SystemExit(23)):
                with self.subTest(error=type(error).__name__):
                    seen = []
                    output, errors = io.StringIO(), io.StringIO()
                    args = mock.Mock(expected_revision=REVISION)

                    def parse(argv):
                        seen.append(signal.getsignal(signal.SIGTERM))
                        if error is not None:
                            raise error
                        return args

                    parser = mock.Mock()
                    parser.parse_args.side_effect = parse
                    with mock.patch.object(encrypt, "argument_parser", return_value=parser), \
                            mock.patch.object(encrypt, "encrypt_private_directory",
                                              return_value=encrypt._summary(REVISION, passed=True)), \
                            redirect_stdout(output), redirect_stderr(errors):
                        if isinstance(error, SystemExit):
                            with self.assertRaises(SystemExit) as caught:
                                encrypt.main([])
                            self.assertIs(caught.exception, error)
                        else:
                            self.assertEqual(encrypt.main([]), int(error is not None))
                    self.assertEqual(len(seen), 1)
                    self.assertTrue(callable(seen[0]))
                    self.assertIsNot(seen[0], enclosing)
                    self.assertIs(signal.getsignal(signal.SIGTERM), enclosing)
                    self.assertIs(signal.getsignal(signal.SIGINT), sigint)
                    self.assertEqual(errors.getvalue(), "")
                    self.assertNotIn("PRIVATE_TOKEN", output.getvalue())
        finally:
            signal.signal(signal.SIGTERM, previous)

    def test_direct_api_remains_usable_in_worker_thread_without_signal_changes(self):
        with encryption_fixture() as fixture:
            results, failures = [], []

            def run():
                try:
                    results.append(fixture.run_encrypt())
                except BaseException as error:
                    failures.append(error)

            with mock.patch.object(encrypt, "MAX_RUNTIME_SECONDS", 2), \
                    mock.patch.object(encrypt.signal, "signal", side_effect=AssertionError("signal mutation")) as install:
                worker = threading.Thread(target=run, daemon=True)
                worker.start()
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
                install.assert_not_called()
            self.assertEqual(failures, [])
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0]["encryption_passed"])


if __name__ == "__main__":
    unittest.main()
