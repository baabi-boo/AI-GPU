# SPDX-License-Identifier: Apache-2.0
"""Offline metadata transport controls, including a blocked resolver child."""

import http.client
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import traceback
import unittest
from unittest import mock

import p06_governance_api as api
import p06_qualified_warm_hosted as hosted


PATH = api.API_PREFIX + "runs/123"
TOKEN = "fixture_token_DO_NOT_PRINT"


def _fixture_launcher(code, launches):
    original = subprocess.Popen

    def launch(argv, **kwargs):
        process = original([argv[0], "-I", "-B", "-S", "-c", code], **kwargs)
        launches.append((argv, kwargs, process))
        return process

    return launch


class GovernanceApiTests(unittest.TestCase):
    def assert_sanitized(self, error):
        rendered = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        self.assertNotIn(TOKEN, rendered)
        self.assertNotIn("PRIVATE-DIAGNOSTIC", rendered)

    def test_hosted_delegates_every_request_and_retains_the_helper(self):
        document = {"id": 123}
        with mock.patch.object(api, "request", return_value=document) as request:
            self.assertIs(hosted._api(PATH, TOKEN), document)
        request.assert_called_once_with(PATH, TOKEN)
        self.assertIn("ci/project/p06_governance_api.py", hosted.SOURCE_FILES)
        self.assertIn("ci/project/baseline_packet_io.py", hosted.SOURCE_FILES)
        self.assertEqual(api.MAX_API_BYTES, hosted.MAX_API_BYTES)

    def test_isolated_worker_uses_closed_environment_and_stdin_only_for_token(self):
        code = """
import json, os, sys
value = json.loads(sys.stdin.buffer.read(4097))
assert type(value['token']) is str and value['token']
json.dump({'path': value['path'], 'keys': sorted(value), 'cwd': os.getcwd(),
           'environment': dict(os.environ), 'isolated': bool(sys.flags.isolated),
           'no_site': bool(sys.flags.no_site), 'no_bytecode': sys.dont_write_bytecode}, sys.stdout)
"""
        launches = []
        ambient = {"GITHUB_TOKEN": TOKEN, "HTTPS_PROXY": "https://PRIVATE-DIAGNOSTIC.invalid",
                   "http_proxy": "http://PRIVATE-DIAGNOSTIC.invalid", "SSLKEYLOGFILE": "PRIVATE-DIAGNOSTIC",
                   "SSL_CERT_FILE": "PRIVATE-DIAGNOSTIC", "SSL_CERT_DIR": "PRIVATE-DIAGNOSTIC",
                   "PYTHONPATH": "PRIVATE-DIAGNOSTIC", "PYTHONSTARTUP": "PRIVATE-DIAGNOSTIC"}
        with mock.patch.dict(os.environ, ambient), \
                mock.patch.object(api.subprocess, "Popen", side_effect=_fixture_launcher(code, launches)):
            result = api.request(PATH, TOKEN)
        argv, kwargs, process = launches[0]
        self.assertEqual(argv, [sys.executable, "-I", "-B", "-S", str(Path(api.__file__).resolve()), "--request"])
        self.assertNotIn(TOKEN, repr(argv) + repr(kwargs))
        self.assertEqual(kwargs["env"], {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "TZ": "UTC"})
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
        self.assertTrue(kwargs["close_fds"])
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(result, {"path": PATH, "keys": ["path", "token"], "cwd": "/",
                                 "environment": kwargs["env"], "isolated": True,
                                 "no_site": True, "no_bytecode": True})
        self.assertEqual(process.returncode, 0)
        self.assertEqual(api.REQUEST_SECONDS, 20)

    def test_parent_kills_and_reaps_a_genuinely_blocked_resolver(self):
        launches = []
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "resolver-entered"
            code = f"""
import runpy, socket, sys, time
def blocked_resolver(*args, **kwargs):
    with open({str(marker)!r}, 'wb') as stream:
        stream.write(b'entered')
    time.sleep(5)
    raise OSError('bounded resolver fixture ended')
socket.getaddrinfo = blocked_resolver
sys.argv = [{str(Path(api.__file__).resolve())!r}, '--request']
runpy.run_path(sys.argv[0], run_name='__main__')
"""
            started = time.monotonic()
            with mock.patch.object(api, "REQUEST_SECONDS", 1.0), \
                    mock.patch.object(api.subprocess, "Popen", side_effect=_fixture_launcher(code, launches)), \
                    self.assertRaisesRegex(api.GovernanceApiError, "^api_timeout$") as raised:
                api.request(PATH, TOKEN)
            elapsed = time.monotonic() - started
            self.assertEqual(marker.read_bytes(), b"entered")
        process = launches[0][2]
        self.assertEqual(process.returncode, -signal.SIGKILL)
        self.assertLess(elapsed, 3.0)
        with self.assertRaises(ChildProcessError):
            os.waitpid(process.pid, os.WNOHANG)
        self.assert_sanitized(raised.exception)

    def test_parent_caps_stdout_before_accumulating_oversized_worker_output(self):
        code = "import sys,time; sys.stdin.buffer.read(); sys.stdout.buffer.write(b'x'*1024); sys.stdout.buffer.flush(); time.sleep(5)"
        launches = []
        with mock.patch.object(api, "MAX_API_BYTES", 64), \
                mock.patch.object(api.subprocess, "Popen", side_effect=_fixture_launcher(code, launches)), \
                self.assertRaisesRegex(api.GovernanceApiError, "^api_bound$") as raised:
            api.request(PATH, TOKEN)
        process = launches[0][2]
        self.assertEqual(process.returncode, -signal.SIGKILL)
        with self.assertRaises(ChildProcessError):
            os.waitpid(process.pid, os.WNOHANG)
        self.assert_sanitized(raised.exception)

    def test_exit_wait_after_stdout_eof_has_the_same_deadline(self):
        code = "import os,sys,time; sys.stdin.buffer.read(); os.close(1); time.sleep(5)"
        launches = []
        started = time.monotonic()
        with mock.patch.object(api, "REQUEST_SECONDS", 0.2), \
                mock.patch.object(api.subprocess, "Popen", side_effect=_fixture_launcher(code, launches)), \
                self.assertRaises(api.GovernanceApiError) as raised:
            api.request(PATH, TOKEN)
        self.assertEqual(launches[0][2].returncode, -signal.SIGKILL)
        self.assertLess(time.monotonic() - started, 3.0)
        self.assert_sanitized(raised.exception)

    def test_launch_errors_and_child_diagnostics_never_escape(self):
        with mock.patch.object(api.subprocess, "Popen", side_effect=OSError("PRIVATE-DIAGNOSTIC " + TOKEN)), \
                self.assertRaisesRegex(api.GovernanceApiError, "^api_request$") as raised:
            api.request(PATH, TOKEN)
        self.assert_sanitized(raised.exception)
        code = "import sys; value=sys.stdin.buffer.read(); sys.stderr.buffer.write(b'PRIVATE-DIAGNOSTIC '+value); sys.exit(2)"
        launches = []
        with mock.patch.object(api.subprocess, "Popen", side_effect=_fixture_launcher(code, launches)), \
                self.assertRaisesRegex(api.GovernanceApiError, "^api_worker$") as raised:
            api.request(PATH, TOKEN)
        self.assert_sanitized(raised.exception)
        self.assertEqual(launches[0][2].returncode, 2)

    def test_parent_rejects_ambiguous_nonfinite_or_nonobject_worker_json(self):
        for body in (b"", b"[]", b'{"id":1,"id":2}', b'{"n":NaN}', b'{"n":1e9999}', b"\xff"):
            with self.subTest(body=body), mock.patch.object(api, "_run_worker", return_value=body), \
                    self.assertRaises(api.GovernanceApiError) as raised:
                api.request(PATH, TOKEN)
            self.assert_sanitized(raised.exception)
        with mock.patch.object(api, "_run_worker", return_value=b'{"id":123,"details":{"ok":true}}'):
            self.assertEqual(api.request(PATH, TOKEN), {"id": 123, "details": {"ok": True}})

    def test_path_and_token_validation_precede_any_worker_or_network(self):
        paths = (None, "", "https://api.github.com" + PATH, "//api.github.com" + PATH,
                 PATH.replace("baabi-boo", "fork"), PATH + "\r\nInjected: value", PATH + "#fragment",
                 api.API_PREFIX + "../issues", api.API_PREFIX + "%2e%2e/issues",
                 api.API_PREFIX + "runs//123", api.API_PREFIX + "runs\\123",
                 PATH + "?a=1?other=2", PATH + "?a=%0a", PATH + "x" * api.MAX_PATH_BYTES)
        for path in paths:
            with self.subTest(path=path), mock.patch.object(api, "_run_worker") as worker, \
                    mock.patch.object(api, "build_opener") as network, \
                    self.assertRaisesRegex(api.GovernanceApiError, "^api_path$"):
                api.request(path, TOKEN)
            worker.assert_not_called()
            network.assert_not_called()
        for token in (None, "", "x\r\nInjected: value", "x" * 257):
            with self.subTest(token=token), mock.patch.object(api, "_run_worker") as worker, \
                    self.assertRaisesRegex(api.GovernanceApiError, "^api_token$"):
                api.request(PATH, token)
            worker.assert_not_called()

    def test_existing_governance_and_artifact_endpoint_shapes_remain_allowed(self):
        suffixes = ("workflows/project-governance.yml", "workflows/project-governance.yml/runs?head_sha="
                    + "a" * 40 + "&status=completed&per_page=100", "runs/123",
                    "runs/123/attempts/2/jobs?per_page=100", "runs/123/artifacts?per_page=100&page=11",
                    "artifacts/456")
        for suffix in suffixes:
            with self.subTest(suffix=suffix), mock.patch.object(api, "_run_worker", return_value=b"{}"):
                self.assertEqual(api.request(api.API_PREFIX + suffix, TOKEN), {})

    def test_network_uses_exact_origin_no_proxy_and_one_bounded_read(self):
        response = mock.MagicMock(status=200)
        response.read.return_value = b'{"id":123}'
        opener = mock.Mock()
        opener.open.return_value.__enter__ = mock.Mock(return_value=response)
        opener.open.return_value.__exit__ = mock.Mock(return_value=False)
        with mock.patch.object(api, "build_opener", return_value=opener) as factory:
            self.assertEqual(api._network_bytes(PATH, TOKEN), b'{"id":123}')
        proxy = next(handler for handler in factory.call_args.args if isinstance(handler, api.ProxyHandler))
        self.assertEqual(proxy.proxies, {})
        self.assertTrue(any(isinstance(handler, api._NoRedirect) for handler in factory.call_args.args))
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, api.API_ORIGIN + PATH)
        self.assertEqual(request.get_header("Authorization"), "Bearer " + TOKEN)
        self.assertEqual(opener.open.call_args.kwargs, {"timeout": 20})
        response.read.assert_called_once_with(api.MAX_API_BYTES + 1)

    def test_redirects_cannot_send_authorization_to_a_second_host(self):
        for status in (301, 302, 303, 307, 308):
            connections = []

            class Socket:
                def makefile(self, _mode):
                    return io.BytesIO((f"HTTP/1.1 {status} Redirect\r\n"
                                       "Location: https://PRIVATE-DIAGNOSTIC.invalid/path\r\n"
                                       "Content-Length: 0\r\n\r\n").encode("ascii"))

                def sendall(self, _body):
                    pass

                def close(self):
                    pass

            def connect(connection):
                connections.append(connection.host)
                connection.sock = Socket()

            with self.subTest(status=status), \
                    mock.patch.object(http.client.HTTPSConnection, "connect", new=connect), \
                    self.assertRaisesRegex(api.GovernanceApiError, "^api_redirect$"):
                api._network_bytes(PATH, TOKEN)
            self.assertEqual(connections, ["api.github.com"])

    def test_network_rejects_bad_status_oversize_and_ambiguous_json(self):
        for status, body in ((403, b"{}"), (200, b"x" * 65), (200, b"[]"),
                             (200, b'{"id":1,"id":2}'), (200, b'{"n":Infinity}')):
            response = mock.MagicMock(status=status)
            response.read.return_value = body
            opener = mock.MagicMock()
            opener.open.return_value.__enter__.return_value = response
            with self.subTest(status=status, body=body), mock.patch.object(api, "MAX_API_BYTES", 64), \
                    mock.patch.object(api, "build_opener", return_value=opener), self.assertRaises(ValueError):
                api._network_bytes(PATH, TOKEN)

    def test_worker_requires_exact_bounded_strict_stdin_and_suppresses_errors(self):
        valid = json.dumps({"path": PATH, "token": TOKEN}).encode("ascii")
        bodies = (b"", b"x" * (api.MAX_REQUEST_BYTES + 1), b"[]", b'{"path":"x","path":"y","token":"z"}',
                  b'{"path":"x","token":NaN}', valid[:-1] + b',"extra":1}')
        for body in bodies:
            stdout, stderr = io.BytesIO(), io.StringIO()
            with self.subTest(body=body[:64]), mock.patch.object(sys, "argv", [api.__file__, "--request"]), \
                    mock.patch.object(sys, "stdin", mock.Mock(buffer=io.BytesIO(body))), \
                    mock.patch.object(sys, "stdout", mock.Mock(buffer=stdout)), \
                    mock.patch.object(sys, "stderr", stderr), mock.patch.object(api, "_network_bytes") as network:
                self.assertEqual(api._main(), 2)
            network.assert_not_called()
            self.assertEqual(stdout.getvalue(), b"")
            self.assertEqual(stderr.getvalue(), "")
        stdout, stderr = io.BytesIO(), io.StringIO()
        with mock.patch.object(sys, "argv", [api.__file__, "--request"]), \
                mock.patch.object(sys, "stdin", mock.Mock(buffer=io.BytesIO(valid))), \
                mock.patch.object(sys, "stdout", mock.Mock(buffer=stdout)), \
                mock.patch.object(sys, "stderr", stderr), \
                mock.patch.object(api, "_network_bytes", side_effect=OSError("PRIVATE-DIAGNOSTIC " + TOKEN)):
            self.assertEqual(api._main(), 2)
        self.assertEqual(stdout.getvalue(), b"")
        self.assertEqual(stderr.getvalue(), "")

    def test_actual_isolated_worker_rejects_invalid_stdin_without_diagnostics(self):
        result = subprocess.run([sys.executable, "-I", "-B", "-S", str(Path(api.__file__).resolve()), "--request"],
                                input=b'{"path":"https://PRIVATE-DIAGNOSTIC.invalid","token":"fixture"}',
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=api._ENVIRONMENT,
                                cwd="/", timeout=5, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout + result.stderr, b"")


if __name__ == "__main__":
    unittest.main()
