# SPDX-License-Identifier: Apache-2.0
"""Bound each authenticated GitHub metadata request in an isolated worker."""

import json
import os
from pathlib import Path
import re
import selectors
import ssl
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from baseline_packet_io import load_json_bytes


API_ORIGIN = "https://api.github.com"
API_PREFIX = "/repos/baabi-boo/AI-GPU/actions/"
MAX_API_BYTES = 4 * 1024**2
MAX_PATH_BYTES = 2048
MAX_REQUEST_BYTES = 4096
REQUEST_SECONDS = 20
REAP_SECONDS = 5
CHUNK_BYTES = 64 * 1024
_ENVIRONMENT = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "TZ": "UTC"}


class GovernanceApiError(ValueError):
    """A static, public-safe failure code for metadata acquisition."""


def _require(condition, code):
    if not condition:
        raise GovernanceApiError(code)


def _arguments(path, token):
    _require(type(path) is str and 0 < len(path) <= MAX_PATH_BYTES
             and path.startswith(API_PREFIX)
             and re.fullmatch(r"[A-Za-z0-9_./?=&-]+", path), "api_path")
    parsed = urlsplit(path)
    _require(not parsed.scheme and not parsed.netloc and not parsed.fragment
             and all(part not in ("", ".", "..") for part in parsed.path.split("/")[1:])
             and (not parsed.query or re.fullmatch(
                 r"[A-Za-z0-9_-]+=[A-Za-z0-9_.-]+(?:&[A-Za-z0-9_-]+=[A-Za-z0-9_.-]+)*",
                 parsed.query)), "api_path")
    _require(type(token) is str and re.fullmatch(r"[A-Za-z0-9_.-]{1,256}", token), "api_token")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise GovernanceApiError("api_redirect")


def _document(body):
    _require(0 < len(body) <= MAX_API_BYTES, "api_bound")
    return load_json_bytes(body, "provider governance observation")


def _network_bytes(path, token):
    _arguments(path, token)
    request = Request(API_ORIGIN + path, headers={
        "Accept": "application/vnd.github+json", "Authorization": "Bearer " + token,
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "p06-qualified-warm-hosted-v1"})
    # The convenience factory reads SSLKEYLOGFILE; construct the verified context directly.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_default_certs(ssl.Purpose.SERVER_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context, debuglevel=0), _NoRedirect())
    with opener.open(request, timeout=REQUEST_SECONDS) as response:
        _require(response.status == 200, "api_status")
        body = response.read(MAX_API_BYTES + 1)
    _document(body)
    return body


def _run_worker(body):
    process = None
    deadline = time.monotonic() + REQUEST_SECONDS
    try:
        process = subprocess.Popen(
            [sys.executable, "-I", "-B", "-S", str(Path(__file__).resolve()), "--request"],
            cwd="/", env=_ENVIRONMENT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True, bufsize=0)
        os.set_blocking(process.stdin.fileno(), False)
        os.set_blocking(process.stdout.fileno(), False)
        pending, output = memoryview(body), bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdin, selectors.EVENT_WRITE)
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                _require(remaining > 0, "api_timeout")
                for key, _ in selector.select(remaining):
                    if key.fileobj is process.stdin:
                        count = os.write(process.stdin.fileno(), pending)
                        _require(count > 0, "api_worker")
                        pending = pending[count:]
                        if not pending:
                            selector.unregister(process.stdin)
                            process.stdin.close()
                    else:
                        chunk = os.read(process.stdout.fileno(),
                                        min(CHUNK_BYTES, MAX_API_BYTES - len(output) + 1))
                        _require(len(chunk) <= MAX_API_BYTES - len(output), "api_bound")
                        if not chunk:
                            selector.unregister(process.stdout)
                            process.stdout.close()
                        else:
                            output.extend(chunk)
        remaining = deadline - time.monotonic()
        _require(remaining > 0, "api_timeout")
        process.wait(timeout=remaining)
        _require(process.returncode == 0, "api_worker")
        return bytes(output)
    finally:
        if process is not None:
            try:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=REAP_SECONDS)
            finally:
                process.stdin.close()
                process.stdout.close()


def request(path, token):
    """Return one strict metadata object within its own supervised wall deadline."""
    try:
        _arguments(path, token)
        body = json.dumps({"path": path, "token": token}, separators=(",", ":")).encode("ascii")
        _require(0 < len(body) <= MAX_REQUEST_BYTES, "api_bound")
        return _document(_run_worker(body))
    except GovernanceApiError:
        raise
    except Exception:
        raise GovernanceApiError("api_request") from None


def _main():
    try:
        _require(len(sys.argv) == 2 and sys.argv[1] == "--request", "api_worker")
        body = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        _require(0 < len(body) <= MAX_REQUEST_BYTES, "api_bound")
        value = load_json_bytes(body, "metadata request")
        _require(set(value) == {"path", "token"}, "api_worker")
        body = _network_bytes(value["path"], value["token"])
        sys.stdout.buffer.write(body)
        sys.stdout.buffer.flush()
        return 0
    except BaseException:
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
