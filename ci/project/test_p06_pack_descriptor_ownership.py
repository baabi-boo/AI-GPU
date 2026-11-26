# SPDX-License-Identifier: Apache-2.0
"""Host-only ownership regressions for private archive input and output."""

import errno
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import p06_qualified_warm_pack as pack


def _audit_probe(direction, error_name, repeated):
    import resource

    check = unittest.TestCase()
    failure = {"OSError": OSError, "RuntimeError": RuntimeError,
               "MemoryError": MemoryError, "KeyboardInterrupt": KeyboardInterrupt}[error_name](
                   "stream construction rejected")
    injected = []
    enabled = True

    def audit(event, args):
        if enabled and event == "open" and type(args[0]) is int:
            injected.append(args[0])
            raise failure

    with tempfile.TemporaryDirectory(prefix="pack-descriptor-") as temporary:
        root = Path(temporary)
        source = root / "input"
        source.write_bytes(b"bounded input\n")
        attempts = 1
        if repeated:
            soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            budget = 64 if soft == resource.RLIM_INFINITY else min(soft, 64)
            resource.setrlimit(resource.RLIMIT_NOFILE, (budget, hard))
            attempts = budget * 2
        sys.addaudithook(audit)
        try:
            for index in range(attempts):
                with check.assertRaises(BaseException) as caught:
                    if direction == "read":
                        pack._read_file(source, contents=True)
                    else:
                        with pack._exclusive(root / ("output-" + str(index))):
                            check.fail("a refused stream cannot be yielded")
                check.assertIs(caught.exception, failure)
                check.assertEqual(len(injected), index + 1)
                with check.assertRaises(OSError) as closed:
                    os.fstat(injected[-1])
                check.assertEqual(closed.exception.errno, errno.EBADF)
        finally:
            enabled = False
            # The old-source negative control must not leak into process cleanup.
            for descriptor in set(injected):
                try:
                    os.fstat(descriptor)
                except OSError:
                    continue
                os.close(descriptor)
    print("archive descriptor ownership verified")


class PackDescriptorOwnershipTests(unittest.TestCase):
    def probe(self, direction, error, *, repeated=False):
        result = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--audit-probe",
             direction, error, str(int(repeated))],
            capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "archive descriptor ownership verified\n")

    def test_reader_fdopen_audit_rejection_releases_descriptor(self):
        for error in ("OSError", "RuntimeError", "MemoryError", "KeyboardInterrupt"):
            with self.subTest(error=error):
                self.probe("read", error)

    def test_output_fdopen_audit_rejection_releases_descriptor(self):
        for error in ("OSError", "RuntimeError", "MemoryError", "KeyboardInterrupt"):
            with self.subTest(error=error):
                self.probe("write", error)

    def test_repeated_reader_rejections_do_not_exhaust_descriptors(self):
        self.probe("read", "RuntimeError", repeated=True)

    def test_repeated_output_rejections_do_not_exhaust_descriptors(self):
        self.probe("write", "RuntimeError", repeated=True)

    def cleanup_case(self, direction, target, primary, failure_type=OSError):
        real_fdopen, real_close, real_directory = os.fdopen, os.close, pack._directory
        owned, reused, streams = {}, [], []
        cleanup_error = failure_type("owned close failed")
        injected = False

        class Stream:
            def __init__(self, stream):
                self.stream = stream
                self.closes = 0

            def __getattr__(self, name):
                return getattr(self.stream, name)

            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.close()

            def read(self, size):
                if primary is not None:
                    raise primary
                return self.stream.read(size)

            def close(self):
                self.closes += 1
                self.stream.close()
                if target == "stream":
                    raise cleanup_error

        def directory(path):
            descriptor = real_directory(path)
            owned["parent"] = descriptor
            return descriptor

        def fdopen(descriptor, *args, **kwargs):
            owned["descriptor"] = descriptor
            result = Stream(real_fdopen(descriptor, *args, **kwargs))
            streams.append(result)
            return result

        def close(descriptor):
            nonlocal injected
            real_close(descriptor)
            if target != "stream" and descriptor == owned.get(target) and not injected:
                injected = True
                witness = os.open(os.devnull, os.O_RDONLY)
                reused.append(witness)
                self.assertEqual(witness, descriptor)
                raise cleanup_error

        with tempfile.TemporaryDirectory(prefix="pack-cleanup-") as temporary:
            root = Path(temporary)
            source = root / "input"
            source.write_bytes(b"retained original")
            try:
                with mock.patch.object(pack, "_directory", side_effect=directory), \
                        mock.patch.object(pack.os, "fdopen", side_effect=fdopen), \
                        mock.patch.object(pack.os, "close", side_effect=close):
                    with self.assertRaises(BaseException) as caught:
                        if direction == "read":
                            pack._read_file(source, contents=True)
                        else:
                            with pack._exclusive(root / "output") as stream:
                                stream.write(b"partial archive")
                                if primary is not None:
                                    raise primary
                    self.assertIs(caught.exception, primary if primary is not None else cleanup_error)
                self.assertEqual(len(streams), 1)
                self.assertEqual(streams[0].closes, 1)
                self.assertTrue(streams[0].stream.closed)
                for descriptor in owned.values():
                    if descriptor not in reused:
                        with self.assertRaises(OSError) as caught:
                            os.fstat(descriptor)
                        self.assertEqual(caught.exception.errno, errno.EBADF)
                for descriptor in reused:
                    os.fstat(descriptor)
                if direction == "write":
                    self.assertEqual((root / "output").read_bytes(), b"partial archive")
            finally:
                for descriptor in reused:
                    real_close(descriptor)
                for descriptor in set(owned.values()) - set(reused):
                    try:
                        os.fstat(descriptor)
                    except OSError:
                        continue
                    real_close(descriptor)

    def test_reader_preserves_primary_failure_and_drains_owned_resources(self):
        for target in ("stream", "descriptor", "parent"):
            for primary in (OSError("read failed"), KeyboardInterrupt("read interrupted")):
                with self.subTest(target=target, primary=type(primary).__name__):
                    self.cleanup_case("read", target, primary)

    def test_output_preserves_primary_failure_and_drains_owned_resources(self):
        for target in ("stream", "descriptor", "parent"):
            for primary in (OSError("write failed"), KeyboardInterrupt("write interrupted")):
                with self.subTest(target=target, primary=type(primary).__name__):
                    self.cleanup_case("write", target, primary)

    def test_successful_read_still_reports_cleanup_failure(self):
        for target in ("stream", "descriptor", "parent"):
            for failure in (OSError, KeyboardInterrupt):
                with self.subTest(target=target, failure=failure.__name__):
                    self.cleanup_case("read", target, None, failure)

    def test_successful_output_still_reports_cleanup_failure(self):
        for target in ("stream", "descriptor", "parent"):
            for failure in (OSError, KeyboardInterrupt):
                with self.subTest(target=target, failure=failure.__name__):
                    self.cleanup_case("write", target, None, failure)

    def test_normal_read_and_write_preserve_borrowed_directory(self):
        with tempfile.TemporaryDirectory(prefix="pack-borrowed-") as temporary:
            root = Path(temporary)
            path = root / "output"
            body = b"complete private archive bytes"
            parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                with pack._exclusive(path, directory_fd=parent) as stream:
                    stream.write(body)
                    descriptor = stream.fileno()
                with self.assertRaises(OSError):
                    os.fstat(descriptor)
                os.fstat(parent)
                row, contents = pack._read_file(path, directory_fd=parent, contents=True)
                self.assertEqual(contents, body)
                self.assertEqual(row.sha256, hashlib.sha256(body).hexdigest())
                self.assertEqual(row.size_bytes, len(body))
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                os.fstat(parent)
            finally:
                os.close(parent)


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--audit-probe":
        _audit_probe(sys.argv[2], sys.argv[3], sys.argv[4] == "1")
    else:
        unittest.main()
