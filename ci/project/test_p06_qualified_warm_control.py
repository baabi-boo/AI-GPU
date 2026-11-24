# SPDX-License-Identifier: Apache-2.0
"""Offline tests of private control transport, byte limits and secret retention."""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import ssl
import stat
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

import p06_qualified_warm_control as control
import p06_qualified_warm_inputs as inputs


AZURE = ("https://fixtureaccount.blob.core.windows.net/private/control.zip"
         "?sv=2025-01-05&se=2099-01-01T00%3A00%3A00Z&sp=r&sr=b&spr=https&sig=never-retain-this-secret")
S3_QUERY = ("X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=never-retain-this-secret"
            "&X-Amz-Date=20260101T000000Z&X-Amz-Expires=60&X-Amz-SignedHeaders=host"
            "&X-Amz-Signature=" + "a" * 64)
S3 = "https://fixture-bucket.s3.us-east-1.amazonaws.com/private/control.zip?" + S3_QUERY
BODY = b"PK\x03\x04inert private fixture; never extract or execute"


class Response:
    def __init__(self, body=BODY, *, status=200, headers=None, read_hook=None, piece=7):
        self.body, self.status, self.position = body, status, 0
        self.headers = headers if headers is not None else [
            ("Content-Length", str(len(BODY))), ("Content-Type", "application/zip")]
        self.read_hook, self.piece = read_hook, piece
        self.reads, self.closed = [], False

    def getheaders(self):
        return self.headers

    def read(self, bound):
        self.reads.append(bound)
        if self.read_hook is not None:
            self.read_hook(self)
        if not 0 < bound <= control.CHUNK_BYTES:
            raise AssertionError("unbounded response read")
        result = self.body[self.position:self.position + min(bound, self.piece)]
        self.position += len(result)
        return result


class ControlContractTests(unittest.TestCase):
    def test_production_pin_is_the_unchanged_reviewed_original(self):
        expected = {"sha256": "d3a16e1e6e92a68414f5fdcce564b963dde2e9e801601191d52ceeb974faea6f",
                    "size_bytes": 47632218}
        self.assertEqual(control._reviewed_identity(), expected)
        self.assertEqual(inputs.input_plan()["originals"]["control"], expected)

    def test_changed_proof_cannot_select_a_different_original(self):
        proof = deepcopy(control.qualification.base_proof())
        proof["controls"]["archive"]["sha256"] = "0" * 64
        with mock.patch.object(control.qualification, "base_proof", return_value=proof):
            with self.assertRaises(control.IntakeError) as raised:
                control._reviewed_identity()
        self.assertEqual(raised.exception.code, "proof_mismatch")

    def test_supported_private_storage_shapes(self):
        for location, provider in ((AZURE, "azure_blob"), (S3, "amazon_s3"),
                                   (S3.replace(".s3.us-east-1.", ".s3."), "amazon_s3"),
                                   (S3.replace("us-east-1", "ap-southeast-2"), "amazon_s3")):
            with self.subTest(provider=provider):
                self.assertEqual(control._transport_location(location)[1], provider)

    def test_arbitrary_alias_redirect_and_credential_locations_are_rejected(self):
        invalid = [
            AZURE.replace("https://", "http://"), AZURE.replace("https://", "HTTPS://"),
            "file:///tmp/control.zip", "https://example.com/control.zip", "https://127.0.0.1/control.zip",
            AZURE.replace("fixtureaccount", "bad-account"), AZURE.replace("fixtureaccount", "a" * 25),
            AZURE.replace(".windows.net", ".windows.net.attacker.invalid"),
            AZURE.replace(".windows.net", ".windows.net."), AZURE.replace(".windows.net", ".windows.net:443"),
            AZURE.replace("https://", "https://user:password@"), AZURE + "#fragment-secret", AZURE + "#",
            AZURE + "\n", " " + AZURE, AZURE.replace("/private/", "//private/"),
            AZURE.replace("/private/", "/private/../"), AZURE.replace("/private/", "/private/%2e%2e/"),
            AZURE.replace("/private/", "/private/%5c/"), AZURE.replace("/private/", "/private/%00/"),
            AZURE.replace("/private/", "/private/%GG/"), AZURE.replace("/private/", "/"),
            AZURE.replace("sp=r", "sp=rw"), AZURE.replace("sr=b", "sr=c"),
            AZURE.replace("spr=https", "spr=https,http"), AZURE.replace("sig=", "other="),
            AZURE + "&sig=duplicate", AZURE.split("?")[0], AZURE.replace("sig=", "sig=%GG"),
            S3.replace("fixture-bucket", "fixture.bucket"), S3.replace("fixture-bucket", "xn--bucket"),
            S3.replace(".s3.us-east-1.", ".s3-website-us-east-1."),
            S3.replace(".s3.us-east-1.", ".s3-accelerate."),
            S3.replace(".s3.us-east-1.", ".s3.dualstack.us-east-1."),
            S3.replace("fixture-bucket.s3", "s3"), S3.replace("amazonaws.com", "amazonaws.com.attacker.invalid"),
            S3.replace("AWS4-HMAC-SHA256", "AWS4-HMAC-SHA1"),
            S3.replace("SignedHeaders=host", "SignedHeaders=host%3Bx-amz-extra"),
            S3.replace("Expires=60", "Expires=604801"), S3.replace("Expires=60", "Expires=0"),
            S3.replace("Signature=" + "a" * 64, "Signature=secret"),
        ]
        for index, location in enumerate(invalid):
            with self.subTest(case=index):
                with self.assertRaises(control.IntakeError) as raised:
                    control._transport_location(location)
                self.assertEqual(raised.exception.code, "invalid_url")
                self.assertNotIn("never-retain", str(raised.exception))

    def test_cli_accepts_no_url_pin_proof_or_budget_overrides_and_echoes_no_secret(self):
        for option in ("--url", "--url-env", "--sha256", "--size-bytes", "--source-dir", "--timeout", "--output"):
            with self.subTest(option=option), mock.patch("sys.stdout", new_callable=io.StringIO) as stdout, \
                    mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                self.assertEqual(control.main(["--output-dir", "/unused", option, AZURE]), 1)
                self.assertEqual(json.loads(stdout.getvalue())["reason_code"], "invalid_arguments")
                self.assertNotIn("never-retain", stdout.getvalue() + stderr.getvalue())
                self.assertNotIn("https:", stdout.getvalue() + stderr.getvalue())

    def test_isolated_cli_help_imports_without_network(self):
        environment = {"PATH": os.defpath, "LANG": "C", "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run([sys.executable, "-I", "-B", control.__file__, "--help"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=environment, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIn(b"--output-dir", result.stdout)

    def test_isolated_cli_rejects_a_fake_private_url_without_leaking_it(self):
        environment = {"PATH": os.defpath, "LANG": "C", "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1",
                       control.URL_ENVIRONMENT_VARIABLE: "https://attacker.invalid/never-retain-this-secret?sig=fixture"}
        with tempfile.TemporaryDirectory(prefix="p06-private-cli-") as directory:
            output = Path(directory).resolve() / "intake"
            result = subprocess.run([sys.executable, "-I", "-B", control.__file__, "--output-dir", str(output)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=environment, timeout=10)
            receipt = (output / control.RECEIPT_NAME).read_bytes()
            self.assertFalse((output / control.ARCHIVE_NAME).exists())
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["reason_code"], "invalid_url")
        self.assertEqual(result.stderr, b"")
        for forbidden in (b"never-retain", b"https:", b"attacker.invalid", b"sig="):
            self.assertNotIn(forbidden, result.stdout + result.stderr + receipt)

    def test_https_transport_uses_verified_tls_one_request_and_no_subprocess(self):
        connection = mock.Mock()
        connection.getresponse.return_value = Response(status=302)
        with mock.patch.object(control.http.client, "HTTPSConnection", return_value=connection) as factory, \
                mock.patch("subprocess.Popen", side_effect=AssertionError("no subprocess")), \
                mock.patch.dict(os.environ, {"HTTPS_PROXY": "https://secret.invalid/credential"}):
            with control._open_https(AZURE, timeout=20) as response:
                self.assertEqual(response.status, 302)
        arguments = factory.call_args
        self.assertEqual(arguments.args, ("fixtureaccount.blob.core.windows.net",))
        self.assertEqual(arguments.kwargs["port"], 443)
        self.assertEqual(arguments.kwargs["timeout"], 20)
        context = arguments.kwargs["context"]
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertEqual(connection.request.call_count, 1)
        self.assertEqual(connection.request.call_args.args[0], "GET")
        connection.close.assert_called_once()

    def test_https_transport_ignores_ambient_tls_key_logging_without_environment_changes(self):
        connection = mock.Mock()
        with tempfile.TemporaryDirectory(prefix="p06-private-tls-") as directory:
            keylog = Path(directory) / "session-keys.log"
            with mock.patch.dict(os.environ, {"SSLKEYLOGFILE": str(keylog)}), \
                    mock.patch.object(control.http.client, "HTTPSConnection", return_value=connection) as factory:
                with control._open_https(AZURE, timeout=20):
                    context = factory.call_args.kwargs["context"]
                    self.assertIsNone(context.keylog_filename)
                    self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
                    self.assertTrue(context.check_hostname)
                    self.assertGreater(context.cert_store_stats()["x509_ca"], 0)
                    self.assertEqual(os.environ["SSLKEYLOGFILE"], str(keylog))
            self.assertFalse(keylog.exists())

    def test_https_transport_suppresses_inherited_http_debug_output(self):
        class Socket:
            def makefile(self, _mode):
                return io.BytesIO(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")

            def sendall(self, _body):
                pass

            def close(self):
                pass

        def connect(connection):
            connection.sock = Socket()

        with mock.patch.object(control.http.client.HTTPConnection, "debuglevel", 1), \
                mock.patch.object(control.http.client.HTTPSConnection, "connect", new=connect), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with control._open_https(AZURE, timeout=20) as response:
                self.assertEqual(response.status, 200)
            self.assertEqual(stdout.getvalue() + stderr.getvalue(), "")


class PrivateControlIntakeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-private-control-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.output = self.root / "intake"
        self.expected = {"sha256": hashlib.sha256(BODY).hexdigest(), "size_bytes": len(BODY)}
        self.pin = self.enterContext(mock.patch.object(control, "_reviewed_identity", return_value=self.expected))
        self.capacity = self.enterContext(mock.patch.object(control.os, "fstatvfs",
            return_value=SimpleNamespace(f_bavail=100 * 1024**3, f_frsize=1)))
        self.enterContext(mock.patch.dict(os.environ, {control.URL_ENVIRONMENT_VARIABLE: AZURE}))
        self.enterContext(mock.patch("subprocess.Popen", side_effect=AssertionError("no subprocess")))
        self.calls = []

    def acquire(self, response=None, *, error=None):
        response = response if response is not None else Response()

        @contextmanager
        def opener(value, *, timeout):
            self.calls.append((value, timeout))
            self.assertNotIn(control.URL_ENVIRONMENT_VARIABLE, os.environ)
            if error is not None:
                raise error
            try:
                yield response
            finally:
                response.closed = True

        return control.acquire_control(self.output, opener=opener)

    def receipt(self):
        body = (self.output / control.RECEIPT_NAME).read_text()
        for forbidden in ("never-retain", "https:", "fixtureaccount", "private/control", "sig=", "X-Amz-"):
            self.assertNotIn(forbidden, body)
        return json.loads(body)

    def assert_failure(self, report, code, *, body=None):
        self.assertNotEqual(report["outcome"], "pass")
        self.assertEqual(report["reason_code"], code)
        self.assertFalse(report["original_verified"])
        self.assertEqual(self.receipt(), report)
        self.assertEqual(report["native_execution"], "not_run")
        if body is not None:
            path = self.output / control.ARCHIVE_NAME
            self.assertEqual(path.read_bytes(), body)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(report["retained_original"]["size_bytes"], len(body))
            self.assertEqual(report["retained_original"]["sha256"], hashlib.sha256(body).hexdigest())
            self.assertEqual(report["retained_state"], "partial")

    def test_success_retains_exact_bytes_with_private_unlinked_outputs_and_no_claims(self):
        response = Response()
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            report = self.acquire(response)
        self.assertEqual(report["outcome"], "pass")
        self.assertTrue(report["original_verified"])
        self.assertEqual(report["retained_state"], "verified")
        self.assertEqual(report["retained_original"], dict(self.expected, path=control.ARCHIVE_NAME))
        self.assertEqual((self.output / control.ARCHIVE_NAME).read_bytes(), BODY)
        self.assertEqual(self.receipt(), report)
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o700)
        for name in (control.ARCHIVE_NAME, control.RECEIPT_NAME):
            self.assertEqual(stat.S_IMODE((self.output / name).stat().st_mode), 0o600)
            self.assertEqual((self.output / name).stat().st_nlink, 1)
        self.assertEqual(set(path.name for path in self.output.iterdir()), {control.ARCHIVE_NAME, control.RECEIPT_NAME})
        self.assertEqual(self.calls, [(AZURE, control.CONNECT_TIMEOUT_SECONDS)])
        self.assertTrue(response.closed)
        self.assertEqual(stdout.getvalue() + stderr.getvalue(), "")
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))
        for field in (*control.dependency.FALSE_CLAIMS, "retained_code_executed", "archive_extracted", "archive_repacked"):
            self.assertIs(report[field], False)

    def test_private_s3_success(self):
        os.environ[control.URL_ENVIRONMENT_VARIABLE] = S3
        report = self.acquire()
        self.assertEqual(report["provider"], "amazon_s3")
        self.assertEqual(report["outcome"], "pass")
        self.receipt()

    def test_missing_secret_is_a_sanitized_blocked_receipt(self):
        os.environ.pop(control.URL_ENVIRONMENT_VARIABLE)
        report = self.acquire()
        self.assert_failure(report, "missing_url")
        self.assertEqual(self.calls, [])
        self.assertFalse((self.output / control.ARCHIVE_NAME).exists())

    def test_untrusted_url_never_reaches_the_opener(self):
        os.environ[control.URL_ENVIRONMENT_VARIABLE] = "https://attacker.invalid/?secret=never-retain"
        self.assert_failure(self.acquire(), "invalid_url")
        self.assertEqual(self.calls, [])

    def test_proof_rejection_precedes_transport(self):
        self.pin.side_effect = control.IntakeError("proof_mismatch")
        self.assert_failure(self.acquire(), "proof_mismatch")
        self.assertEqual(self.calls, [])

    def test_disk_reserve_is_required_before_transport(self):
        self.capacity.return_value.f_bavail = control.dependency.BUDGET["min_free_bytes"] + len(BODY) - 1
        self.assert_failure(self.acquire(), "insufficient_disk")
        self.assertEqual(self.calls, [])

    def test_existing_root_cannot_be_reused_or_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / control.ARCHIVE_NAME
        sentinel.write_bytes(b"unchanged")
        with self.assertRaises(control.IntakeError) as raised:
            self.acquire()
        self.assertEqual(raised.exception.code, "unsafe_output")
        self.assertEqual(sentinel.read_bytes(), b"unchanged")
        self.assertEqual(self.calls, [])

    def test_symlink_roots_and_ancestors_are_rejected(self):
        existing = self.root / "existing"
        existing.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(existing, target_is_directory=True)
        for target in (alias, alias / "new", self.root / "missing" / "new"):
            with self.subTest(target=target.name), self.assertRaises(control.IntakeError):
                control.acquire_control(target, opener=mock.Mock())
        self.assertEqual(list(existing.iterdir()), [])

    def test_noncanonical_paths_and_source_storage_are_rejected(self):
        for path in ("relative", str(self.root) + "/./new", str(self.root) + "//new",
                     str(self.root) + "/../new", str(control.ROOT / "private-control-uncreated")):
            with self.subTest(path=path), self.assertRaises(control.IntakeError):
                control.acquire_control(path, opener=mock.Mock())

    def test_preexisting_archive_symlink_is_never_opened(self):
        victim = self.root / "victim"
        victim.write_bytes(b"unchanged")
        original_create = control._PrivateOutput.create

        def create(output, name):
            if name == control.ARCHIVE_NAME:
                (output.path / name).symlink_to(victim)
            return original_create(output, name)

        with mock.patch.object(control._PrivateOutput, "create", new=create):
            report = self.acquire()
        self.assert_failure(report, "internal_failure")
        self.assertEqual(victim.read_bytes(), b"unchanged")
        self.assertEqual(self.calls, [])

    def test_archive_hardlink_cannot_be_admitted(self):
        def link_once(response):
            if response.position == 0:
                os.link(self.output / control.ARCHIVE_NAME, self.root / "alias.zip")

        report = self.acquire(Response(read_hook=link_once))
        self.assert_failure(report, "unsafe_retention")
        self.assertTrue(report["retention_identity_unavailable"])

    def test_replaced_archive_path_does_not_change_an_existing_file(self):
        victim = self.root / "victim"
        victim.write_bytes(b"unchanged")

        def replace_once(response):
            if response.position == 0:
                archive = self.output / control.ARCHIVE_NAME
                archive.rename(self.output / "retained-original-bytes")
                archive.symlink_to(victim)

        self.assert_failure(self.acquire(Response(read_hook=replace_once)), "unsafe_retention")
        self.assertEqual(victim.read_bytes(), b"unchanged")

    def test_redirects_and_http_failures_never_retain_response_text(self):
        for status in (301, 302, 303, 307, 308, 401, 403, 404, 500):
            with self.subTest(status=status):
                self.output = self.root / ("status-" + str(status))
                os.environ[control.URL_ENVIRONMENT_VARIABLE] = AZURE
                response = Response(b"raw response text never-retain-this-secret", status=status,
                                    headers=[("Location", AZURE)])
                self.assert_failure(self.acquire(response), "response_rejected", body=b"")
                self.assertEqual(response.reads, [])

    def test_ambiguous_oversized_encoded_and_text_responses_are_rejected_before_read(self):
        normal = [("Content-Length", str(len(BODY))), ("Content-Type", "application/zip")]
        variants = [normal[1:], [("Content-Length", str(len(BODY) + 1)), normal[1]],
                    normal + [normal[0]], normal + [("Transfer-Encoding", "chunked")],
                    normal + [("Content-Encoding", "gzip")], normal + [("Content-Range", "bytes 0-1/99")],
                    [normal[0], ("Content-Type", "text/plain")],
                    [normal[0], ("Content-Type", "application/xml")],
                    [normal[0], ("Content-Type", "application/zip\r\nsecret")]]
        for index, headers in enumerate(variants):
            with self.subTest(case=index):
                self.output = self.root / ("headers-" + str(index))
                os.environ[control.URL_ENVIRONMENT_VARIABLE] = AZURE
                response = Response(headers=headers)
                self.assert_failure(self.acquire(response), "response_rejected", body=b"")
                self.assertEqual(response.reads, [])

    def test_truncation_retains_only_received_bytes(self):
        self.assert_failure(self.acquire(Response(BODY[:13])), "size_mismatch", body=BODY[:13])

    def test_overflow_retains_at_most_exact_expected_size_and_never_passes(self):
        response = Response(BODY + b"unexpected", piece=len(BODY) + 1)
        self.assert_failure(self.acquire(response), "size_mismatch", body=BODY)

    def test_an_opener_cannot_ignore_the_requested_read_bound(self):
        response = Response()
        response.read = lambda _bound: b"x" * (len(BODY) + 2)
        self.assert_failure(self.acquire(response), "response_rejected", body=b"")

    def test_exact_size_does_not_replace_hash_verification(self):
        damaged = b"x" + BODY[1:]
        self.assert_failure(self.acquire(Response(damaged)), "digest_mismatch", body=damaged)

    def test_timeout_retains_partial_bytes_without_exception_details(self):
        def fail_after_first(response):
            if response.position:
                raise TimeoutError(AZURE)

        self.assert_failure(self.acquire(Response(read_hook=fail_after_first)), "timeout", body=BODY[:7])

    def test_transport_error_is_sanitized_and_secret_is_consumed(self):
        self.assert_failure(self.acquire(error=OSError("raw response " + AZURE)), "transport_failed", body=b"")
        self.assertNotIn(control.URL_ENVIRONMENT_VARIABLE, os.environ)

    def test_interrupt_retains_the_actual_partial_archive(self):
        def interrupted(response):
            if response.position:
                raise KeyboardInterrupt(AZURE)

        self.assert_failure(self.acquire(Response(read_hook=interrupted)), "interrupted", body=BODY[:7])

    def test_outer_deadline_stops_a_stalled_fake_reader_and_restores_alarm(self):
        def stalled(_response):
            time.sleep(2)

        previous_handler = signal.getsignal(signal.SIGALRM)
        started = time.monotonic()
        with mock.patch.object(control, "TRANSFER_TIMEOUT_SECONDS", 0.02):
            self.assert_failure(self.acquire(Response(read_hook=stalled)), "timeout", body=b"")
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(signal.getsignal(signal.SIGALRM), previous_handler)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))

    def test_existing_timer_blocks_instead_of_replacing_it(self):
        previous = signal.getitimer(signal.ITIMER_REAL)
        try:
            signal.setitimer(signal.ITIMER_REAL, 60)
            report = self.acquire()
            self.assert_failure(report, "timeout_unavailable", body=b"")
            self.assertEqual(self.calls, [])
            self.assertGreater(signal.getitimer(signal.ITIMER_REAL)[0], 50)
        finally:
            signal.setitimer(signal.ITIMER_REAL, *previous)

    def test_non_main_thread_deadline_is_rejected(self):
        with mock.patch.object(control.threading, "current_thread", return_value=object()):
            self.assert_failure(self.acquire(), "timeout_unavailable", body=b"")
        self.assertEqual(self.calls, [])

    def test_receipt_is_exclusive_and_does_not_overwrite_a_concurrent_file(self):
        sentinel = b"existing receipt must remain unchanged"

        def add_receipt(response):
            if response.position == 0:
                (self.output / control.RECEIPT_NAME).write_bytes(sentinel)

        with self.assertRaises(control.IntakeError) as raised:
            self.acquire(Response(read_hook=add_receipt))
        self.assertEqual(raised.exception.code, "receipt_failed")
        self.assertEqual((self.output / control.RECEIPT_NAME).read_bytes(), sentinel)
        self.assertEqual((self.output / control.ARCHIVE_NAME).read_bytes(), BODY)

    def test_short_local_writes_are_completed_without_changing_original_bytes(self):
        original_write = os.write

        def short_write(descriptor, body):
            return original_write(descriptor, body[:3])

        with mock.patch.object(control.os, "write", side_effect=short_write):
            self.assertEqual(self.acquire()["outcome"], "pass")
        self.assertEqual((self.output / control.ARCHIVE_NAME).read_bytes(), BODY)
        self.receipt()

    def test_terminal_exception_is_sanitized(self):
        with mock.patch.object(control, "acquire_control", side_effect=OSError(AZURE)), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            result = control.main(["--output-dir", str(self.output)])
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(stdout.getvalue())["reason_code"], "internal_failure")
        self.assertNotIn("never-retain", stdout.getvalue() + stderr.getvalue())
        self.assertNotIn("https:", stdout.getvalue() + stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
