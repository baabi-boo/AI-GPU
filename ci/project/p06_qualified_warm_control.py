#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fetch only the reviewed historical control ZIP into a fresh private directory."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import ssl
import stat
import sys
import threading
import time
from urllib.parse import parse_qsl, unquote, urlsplit

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import p06_dependency_contract as dependency
import p06_qualified_warm_contract as qualification


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p06-qualified-warm-private-control-intake-v1"
URL_ENVIRONMENT_VARIABLE = "P06_CONTROL_ARCHIVE_URL"
ARCHIVE_NAME = "control-original.zip"
RECEIPT_NAME = "control-intake.json"
CONTROL_SHA256 = "d3a16e1e6e92a68414f5fdcce564b963dde2e9e801601191d52ceeb974faea6f"
CONTROL_BYTES = 47632218
CONNECT_TIMEOUT_SECONDS = 20
TRANSFER_TIMEOUT_SECONDS = 120
CHUNK_BYTES = 64 * 1024
MAX_URL_BYTES = 16 * 1024
_AZURE_HOST = re.compile(r"[a-z0-9]{3,24}\.blob\.core\.windows\.net\Z")
_S3_HOST = re.compile(
    r"(?P<bucket>[a-z0-9][a-z0-9-]{1,61}[a-z0-9])\.s3"
    r"(?:\.(?:af|ap|ca|eu|il|me|mx|sa|us)-(?:central|east|north|northeast|northwest|south|southeast|southwest|west)-[1-9][0-9]?)?"
    r"\.amazonaws\.com\Z")
_REASONS = {
    "invalid_arguments": "Invalid private intake arguments.",
    "unsafe_output": "A fresh canonical private output directory is required.",
    "missing_url": "The named private control transport environment variable is missing.",
    "invalid_url": "The private control transport must use an allowed canonical signed HTTPS object URL.",
    "proof_mismatch": "The reviewed historical control identity could not be verified.",
    "insufficient_disk": "The control download requires its exact bytes plus the unchanged disk reserve.",
    "timeout_unavailable": "A private transfer requires an unused POSIX main-thread deadline.",
    "timeout": "The private control transfer exceeded its finite deadline.",
    "transport_failed": "The private control transfer failed; response details are withheld.",
    "response_rejected": "The private control response status or framing was rejected.",
    "size_mismatch": "The retained control bytes differ from the exact reviewed size.",
    "digest_mismatch": "The retained control bytes differ from the reviewed SHA-256.",
    "unsafe_retention": "Private output identity, permissions or link checks failed.",
    "storage_failed": "The private control bytes could not be retained safely.",
    "receipt_failed": "The private control receipt could not be retained safely.",
    "interrupted": "The private control intake was interrupted.",
    "internal_failure": "The private control intake failed; internal details are withheld.",
}
LIMITATIONS = [
    "This receipt establishes only an exact original byte intake; admission and independent replay remain required.",
    "The archive is private vendor-containing material; no public redistribution is authorized.",
    "Failed bytes remain at the same archive path and must not be used unless this invocation succeeds and original_verified is true.",
    "No archive member is opened, extracted, executed or repacked, and no subprocess is launched.",
    "A signed storage location does not authenticate a historical CI job or establish acceptance.",
    "Network access remains subject to runner policy; no redirect, proxy override or alternate route is selected.",
    "Private permissions and descriptor checks do not isolate a malicious process with the same user identity.",
]


class IntakeError(ValueError):
    def __init__(self, code):
        self.code = code if code in _REASONS else "internal_failure"
        super().__init__(_REASONS[self.code])


def _require(condition, code):
    if not condition:
        raise IntakeError(code)


def _reviewed_identity():
    try:
        qualification.load_proof(ROOT / qualification.SOURCE_PROOF_PATH,
                                 qualification.SOURCE_PROOF_SHA256)
        original = qualification.base_proof(ROOT)["controls"]["archive"]
        expected = {"sha256": CONTROL_SHA256, "size_bytes": CONTROL_BYTES}
        _require({key: original[key] for key in expected} == expected, "proof_mismatch")
        return expected
    except Exception:
        raise IntakeError("proof_mismatch") from None


def _transport_location(value):
    _require(type(value) is str and 0 < len(value) <= MAX_URL_BYTES
             and value.isascii() and not any(ord(char) <= 32 or ord(char) == 127 for char in value)
             and value.startswith("https://") and "#" not in value and "\\" not in value,
             "invalid_url")
    try:
        parsed = urlsplit(value)
        _require(parsed.scheme == "https" and parsed.netloc == parsed.hostname
                 and parsed.username is None and parsed.password is None and parsed.port is None,
                 "invalid_url")
        azure, s3 = _AZURE_HOST.fullmatch(parsed.netloc), _S3_HOST.fullmatch(parsed.netloc)
        _require(bool(azure or s3), "invalid_url")
        _require(not s3 or not s3["bucket"].startswith(("xn--", "sthree-", "amzn-s3-demo-")),
                 "invalid_url")
        _require(parsed.path.startswith("/") and len(parsed.path) > 1
                 and not re.search(r"%(?![0-9A-Fa-f]{2})", parsed.path + parsed.query), "invalid_url")
        decoded = unquote(parsed.path, errors="strict")
        _require(not any(ord(char) <= 32 or ord(char) == 127 for char in decoded)
                 and "\\" not in decoded and all(part not in ("", ".", "..") for part in decoded[1:].split("/")),
                 "invalid_url")
        if azure:
            _require(len(decoded[1:].split("/")) >= 2, "invalid_url")
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True,
                          encoding="ascii", errors="strict", max_num_fields=32)
        query = dict(pairs)
        _require(len(query) == len(pairs) and all(key and item for key, item in pairs), "invalid_url")
        if azure:
            _require({"sig", "sv", "se", "sp", "sr"} <= query.keys()
                     and query["sp"] == "r" and query["sr"] == "b"
                     and query.get("spr", "https") == "https", "invalid_url")
        else:
            required = {"X-Amz-Algorithm", "X-Amz-Credential", "X-Amz-Date", "X-Amz-Expires",
                        "X-Amz-SignedHeaders", "X-Amz-Signature"}
            _require(required <= query.keys() and query["X-Amz-Algorithm"] == "AWS4-HMAC-SHA256"
                     and query["X-Amz-SignedHeaders"] == "host"
                     and re.fullmatch(r"[0-9a-f]{64}", query["X-Amz-Signature"])
                     and re.fullmatch(r"[1-9][0-9]{0,5}", query["X-Amz-Expires"])
                     and int(query["X-Amz-Expires"]) <= 604800, "invalid_url")
        return parsed, "azure_blob" if azure else "amazon_s3"
    except Exception:
        raise IntakeError("invalid_url") from None


@contextmanager
def _deadline():
    _require(threading.current_thread() is threading.main_thread()
             and hasattr(signal, "setitimer") and hasattr(signal, "ITIMER_REAL"), "timeout_unavailable")
    previous = signal.getitimer(signal.ITIMER_REAL)
    _require(previous == (0.0, 0.0), "timeout_unavailable")
    handler = signal.getsignal(signal.SIGALRM)

    def expired(_signum, _frame):
        raise IntakeError("timeout")

    signal.signal(signal.SIGALRM, expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, TRANSFER_TIMEOUT_SECONDS)
        yield time.monotonic() + TRANSFER_TIMEOUT_SECONDS
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, handler)


@contextmanager
def _open_https(value, *, timeout):
    parsed, _provider = _transport_location(value)
    # The default-context factory can enable ambient TLS session-key logging.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_default_certs(ssl.Purpose.SERVER_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    connection = http.client.HTTPSConnection(parsed.hostname, port=443, timeout=timeout, context=context)
    connection.set_debuglevel(0)
    response, failed = None, False
    try:
        connection.request("GET", parsed.path + "?" + parsed.query,
                           headers={"Accept-Encoding": "identity", "Connection": "close"})
        response = connection.getresponse()
        yield response
    except BaseException:
        failed = True
        raise
    finally:
        close_error = None
        # HTTPConnection relinquishes a response with Connection: close;
        # both resources must close without replacing an active failure.
        for resource in (response, connection):
            if resource is not None:
                try:
                    resource.close()
                except BaseException as error:
                    if close_error is None:
                        close_error = error
        if not failed and close_error is not None:
            raise close_error


def _response_header_check(response, expected):
    _require(type(response.status) is int and response.status == 200, "response_rejected")
    pairs = response.getheaders()
    _require(type(pairs) in (list, tuple) and len(pairs) <= 100, "response_rejected")
    selected = {}
    for key, value in pairs:
        _require(type(key) is str and type(value) is str and len(value) <= 8192
                 and not any(char in value for char in "\r\n\0"), "response_rejected")
        key = key.lower()
        if key in ("content-length", "content-type", "content-encoding", "transfer-encoding", "content-range"):
            _require(key not in selected, "response_rejected")
            selected[key] = value
    _require(selected.get("content-length") == str(expected["size_bytes"])
             and "transfer-encoding" not in selected and "content-range" not in selected
             and selected.get("content-encoding", "identity") == "identity"
             and selected.get("content-type", "").lower() in (
                 "application/zip", "application/x-zip-compressed", "application/octet-stream", "binary/octet-stream"),
             "response_rejected")


def _directory_path(value):
    raw = os.fspath(value)
    _require(type(raw) is str and 0 < len(raw) <= 4096
             and re.fullmatch(r"/[A-Za-z0-9_./+\-]+", raw)
             and str(PurePosixPath(raw)) == raw
             and all(part not in (".", "..") for part in raw.split("/")), "unsafe_output")
    path = Path(raw)
    _require(path != ROOT and ROOT not in path.parents and path != Path("/"), "unsafe_output")
    return path


def _open_directory(path):
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            parent, descriptor = descriptor, child
            os.close(parent)
        return descriptor
    except BaseException:
        try:
            os.close(descriptor)
        except BaseException:
            pass
        raise


def _same_inode(left, right):
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


class _PrivateOutput:
    def __init__(self, value):
        self.path = _directory_path(value)
        self.descriptor = None
        try:
            parent = _open_directory(self.path.parent)
            try:
                os.mkdir(self.path.name, mode=0o700, dir_fd=parent)
                self.descriptor = os.open(self.path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                          dir_fd=parent)
                os.fchmod(self.descriptor, 0o700)
                self.check()
            finally:
                os.close(parent)
        except BaseException:
            self.close()
            raise IntakeError("unsafe_output") from None

    def check(self):
        fresh = _open_directory(self.path)
        try:
            current, actual = os.fstat(fresh), os.fstat(self.descriptor)
            _require(_same_inode(current, actual) and stat.S_IMODE(actual.st_mode) == 0o700
                     and actual.st_uid == os.geteuid(), "unsafe_retention")
        finally:
            os.close(fresh)

    def create(self, name):
        self.check()
        descriptor = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=self.descriptor)
        try:
            os.fchmod(descriptor, 0o600)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def file_status(self, descriptor, name):
        self.check()
        actual = os.fstat(descriptor)
        named = os.stat(name, dir_fd=self.descriptor, follow_symlinks=False)
        _require(_same_inode(actual, named) and stat.S_ISREG(actual.st_mode)
                 and actual.st_nlink == named.st_nlink == 1
                 and stat.S_IMODE(actual.st_mode) == 0o600 and actual.st_uid == os.geteuid(),
                 "unsafe_retention")
        return actual

    def close(self):
        if self.descriptor is not None:
            descriptor, self.descriptor = self.descriptor, None
            os.close(descriptor)


def _write_all(descriptor, body):
    view = memoryview(body)
    while view:
        try:
            written = os.write(descriptor, view)
        except OSError:
            raise IntakeError("storage_failed") from None
        _require(written > 0, "storage_failed")
        view = view[written:]


def _stream(response, descriptor, expected, deadline):
    size = 0
    while True:
        _require(time.monotonic() < deadline, "timeout")
        bound = min(CHUNK_BYTES, expected["size_bytes"] + 1 - size)
        block = response.read(bound)
        _require(type(block) is bytes and len(block) <= bound, "response_rejected")
        if not block:
            break
        remaining = expected["size_bytes"] - size
        _write_all(descriptor, block[:remaining])
        size += min(len(block), remaining)
        _require(len(block) <= remaining, "size_mismatch")
    _require(size == expected["size_bytes"], "size_mismatch")


def _retained_identity(output, descriptor, maximum):
    try:
        os.fsync(descriptor)
        before = output.file_status(descriptor, ARCHIVE_NAME)
        _require(0 <= before.st_size <= maximum, "unsafe_retention")
        os.lseek(descriptor, 0, os.SEEK_SET)
        digest, size = hashlib.sha256(), 0
        while block := os.read(descriptor, min(CHUNK_BYTES, maximum + 1 - size)):
            size += len(block)
            _require(size <= maximum, "unsafe_retention")
            digest.update(block)
        after = output.file_status(descriptor, ARCHIVE_NAME)
        signature = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns,
                                 row.st_ctime_ns, row.st_nlink, row.st_mode)
        _require(signature(before) == signature(after) and size == after.st_size, "unsafe_retention")
        return {"path": ARCHIVE_NAME, "sha256": digest.hexdigest(), "size_bytes": size}
    except OSError:
        raise IntakeError("storage_failed") from None


def _repair_receipt(output, report, owned, *, descriptor=None, directory_owned=None):
    recovered_directory = None
    try:
        if descriptor is None and owned is not None:
            directory = output.descriptor
            if directory is None:
                recovered_directory = directory = _open_directory(output.path)
                actual = os.fstat(directory)
                _require(directory_owned is not None and _same_inode(actual, directory_owned)
                         and stat.S_IMODE(actual.st_mode) == 0o700
                         and actual.st_uid == os.geteuid(), "receipt_failed")
            else:
                output.check()
            named = os.stat(RECEIPT_NAME, dir_fd=directory, follow_symlinks=False)
            _require(_same_inode(named, owned) and stat.S_ISREG(named.st_mode)
                     and named.st_nlink == 1 and stat.S_IMODE(named.st_mode) == 0o600
                     and named.st_uid == os.geteuid(), "receipt_failed")
            descriptor = os.open(RECEIPT_NAME, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=directory)
            actual = os.fstat(descriptor)
            named = os.stat(RECEIPT_NAME, dir_fd=directory, follow_symlinks=False)
            _require(_same_inode(actual, owned) and _same_inode(actual, named)
                     and stat.S_ISREG(actual.st_mode) and actual.st_nlink == named.st_nlink == 1
                     and stat.S_IMODE(actual.st_mode) == 0o600
                     and actual.st_uid == os.geteuid(), "receipt_failed")
        if descriptor is not None:
            # Only an owned inode may be invalidated, even after the original
            # descriptors have been consumed by failing close calls.
            os.ftruncate(descriptor, 0)
            os.lseek(descriptor, 0, os.SEEK_SET)
            failed = dict(report)
            if failed["outcome"] == "pass":
                failed.update(outcome="fail", reason_code="receipt_failed",
                              reason=_REASONS["receipt_failed"], original_verified=False,
                              retained_state="partial")
            _write_all(descriptor, (json.dumps(failed, indent=2, sort_keys=True) + "\n").encode("ascii"))
            os.fsync(descriptor)
    except (Exception, KeyboardInterrupt):
        # Storage failure can also prevent a complete failure receipt.
        pass
    finally:
        for resource in (descriptor, recovered_directory):
            if resource is not None:
                try:
                    os.close(resource)
                except (Exception, KeyboardInterrupt):
                    pass


def _write_receipt(output, report):
    descriptor, owned = None, None
    try:
        descriptor = output.create(RECEIPT_NAME)
        owned = output.file_status(descriptor, RECEIPT_NAME)
        _write_all(descriptor, (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("ascii"))
        os.fsync(descriptor)
        owned = output.file_status(descriptor, RECEIPT_NAME)
        os.fsync(output.descriptor)
        directory_owned = os.fstat(output.descriptor)
        # A failed close may already release the descriptor; never retry it.
        closing, descriptor = descriptor, None
        os.close(closing)
        return owned, directory_owned
    except (Exception, KeyboardInterrupt):
        repairing, descriptor = descriptor, None
        _repair_receipt(output, report, owned, descriptor=repairing)
        raise IntakeError("receipt_failed") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except (Exception, KeyboardInterrupt):
                # Cleanup must not replace the sanitized receipt failure.
                pass


def _close_failure(report, error):
    code = report["reason_code"] or (
        "interrupted" if isinstance(error, KeyboardInterrupt) else "storage_failed")
    if report["outcome"] == "pass":
        report.update(outcome="fail", reason_code=code, reason=_REASONS[code],
                      original_verified=False, retained_state="partial")
    return IntakeError(code)


def acquire_control(output_dir, *, opener=None):
    """Consume the named environment secret; return only a sanitized intake receipt."""
    location = os.environ.pop(URL_ENVIRONMENT_VARIABLE, None)
    output = _PrivateOutput(output_dir)
    descriptor = None
    report = {"schema_version": 1, "contract_id": CONTRACT_ID,
        "scope": "private-historical-control-original-byte-intake-only", "state": "finished",
        "outcome": "blocked", "reason_code": None, "reason": None,
        "expected": {"sha256": CONTROL_SHA256, "size_bytes": CONTROL_BYTES},
        "qualified_warm_proof_sha256": qualification.SOURCE_PROOF_SHA256,
        "historical_proof_sha256": qualification.historical.SOURCE_PROOF_SHA256,
        "transport_environment_variable": URL_ENVIRONMENT_VARIABLE, "provider": None,
        "network_acquisition": False, "retained_original": None, "retained_state": "absent",
        "original_verified": False, "native_execution": "not_run", "retained_code_executed": False,
        "archive_extracted": False, "archive_repacked": False,
        "counter_qualification_passed": False, "qualified_warm_passed": False,
        "budget": {"archive_max_bytes": CONTROL_BYTES, "chunk_bytes": CHUNK_BYTES,
                   "connect_timeout_seconds": CONNECT_TIMEOUT_SECONDS,
                   "transfer_timeout_seconds": TRANSFER_TIMEOUT_SECONDS,
                   "min_free_bytes": dependency.BUDGET["min_free_bytes"]},
        "limitations": list(LIMITATIONS), **dict.fromkeys(dependency.FALSE_CLAIMS, False)}
    try:
        expected = _reviewed_identity()
        report["expected"] = expected
        _require(location is not None, "missing_url")
        _parsed, report["provider"] = _transport_location(location)
        free = os.fstatvfs(output.descriptor)
        _require(free.f_bavail * free.f_frsize >= dependency.BUDGET["min_free_bytes"]
                 + expected["size_bytes"] + CHUNK_BYTES, "insufficient_disk")
        descriptor = output.create(ARCHIVE_NAME)
        output.file_status(descriptor, ARCHIVE_NAME)
        with _deadline() as deadline:
            report["network_acquisition"] = True
            with (opener or _open_https)(location, timeout=CONNECT_TIMEOUT_SECONDS) as response:
                _response_header_check(response, expected)
                _stream(response, descriptor, expected, deadline)
        report["retained_original"] = _retained_identity(output, descriptor, expected["size_bytes"])
        _require(report["retained_original"]["size_bytes"] == expected["size_bytes"], "size_mismatch")
        _require(report["retained_original"]["sha256"] == expected["sha256"], "digest_mismatch")
        _require(_reviewed_identity() == expected, "proof_mismatch")
        _require(set(os.listdir(output.descriptor)) == {ARCHIVE_NAME}, "unsafe_retention")
        report.update(outcome="pass", original_verified=True, retained_state="verified")
    except (Exception, KeyboardInterrupt) as error:
        code = (error.code if isinstance(error, IntakeError) else "interrupted"
                if isinstance(error, KeyboardInterrupt) else "timeout"
                if isinstance(error, TimeoutError) else "transport_failed"
                if report["network_acquisition"] else "internal_failure")
        report.update(outcome="fail" if report["network_acquisition"] else "blocked",
                      reason_code=code, reason=_REASONS[code])
        if descriptor is not None:
            report["retained_state"] = "partial"
            try:
                report["retained_original"] = _retained_identity(output, descriptor, CONTROL_BYTES)
            except (Exception, KeyboardInterrupt):
                report["retention_identity_unavailable"] = True
    finally:
        location = None
        failure, receipt_identity = None, None
        if descriptor is not None:
            closing, descriptor = descriptor, None
            try:
                os.close(closing)
            except (Exception, KeyboardInterrupt) as error:
                failure = _close_failure(report, error)
        try:
            receipt_identity = _write_receipt(output, report)
        except (Exception, KeyboardInterrupt) as error:
            if failure is None:
                failure = error
        finally:
            try:
                output.close()
            except (Exception, KeyboardInterrupt) as error:
                close_error = _close_failure(report, error)
                if failure is None:
                    failure = close_error
                if receipt_identity is not None:
                    owned, directory_owned = receipt_identity
                    _repair_receipt(output, report, owned, directory_owned=directory_owned)
        if failure is not None:
            raise failure from None
    return report


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise IntakeError("invalid_arguments")


def argument_parser():
    parser = _Parser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--output-dir", required=True,
                        help="Fresh absolute private directory outside the source checkout")
    return parser


def main(argv=None):
    try:
        args = argument_parser().parse_args(argv)
        report = acquire_control(args.output_dir)
        summary = {key: report[key] for key in ("contract_id", "outcome", "reason_code", "reason",
                                                "original_verified", "native_execution")}
    except (Exception, KeyboardInterrupt) as error:
        code = error.code if isinstance(error, IntakeError) else "interrupted" if isinstance(error, KeyboardInterrupt) else "internal_failure"
        summary = {"contract_id": CONTRACT_ID, "outcome": "blocked", "reason_code": code,
                   "reason": _REASONS[code], "original_verified": False, "native_execution": "not_run"}
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["outcome"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
