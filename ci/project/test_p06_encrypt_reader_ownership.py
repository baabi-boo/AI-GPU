# SPDX-License-Identifier: Apache-2.0
"""Host-only verified-reader ownership and first-failure checks."""

import errno
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "ci/project/p06_qualified_warm_encrypt.py"


def _load_encrypt(source):
    spec = importlib.util.spec_from_file_location("p06_qualified_warm_encrypt", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _failure(name, message):
    if name == "OSError":
        return OSError(errno.EIO, message)
    if name == "KeyboardInterrupt":
        return KeyboardInterrupt(message)
    raise ValueError(name)


class _Descriptors:
    def __init__(self, check):
        self.check = check
        self.real_open, self.real_close = os.open, os.close
        self.opened = []
        self.reused = {}
        self.failure = self.fail_fd = None
        self.failed_closes = []

    def open(self, *args, **kwargs):
        descriptor = self.real_open(*args, **kwargs)
        info = os.fstat(descriptor)
        self.opened.append((descriptor, (info.st_dev, info.st_ino)))
        return descriptor

    def close(self, descriptor):
        self.real_close(descriptor)
        if self.failure is not None and descriptor == self.fail_fd:
            self.failed_closes.append(descriptor)
            replacement = self.real_open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
            if replacement != descriptor:
                os.dup2(replacement, descriptor, inheritable=False)
                self.real_close(replacement)
            info = os.fstat(descriptor)
            self.reused[descriptor] = (info.st_dev, info.st_ino)
            raise self.failure

    def assert_released(self):
        self.check.assertTrue(self.opened)
        for descriptor in {item[0] for item in self.opened} - self.reused.keys():
            with self.check.assertRaises(OSError) as caught:
                os.fstat(descriptor)
            self.check.assertEqual(caught.exception.errno, errno.EBADF)
        for descriptor, expected in self.reused.items():
            info = os.fstat(descriptor)
            self.check.assertEqual((info.st_dev, info.st_ino), expected)
        if self.failure is not None:
            self.check.assertEqual(self.failed_closes, [self.fail_fd])

    def cleanup(self):
        # Keep failing controls bounded without hiding their release assertions.
        for descriptor, expected in set(self.opened) | set(self.reused.items()):
            try:
                info = os.fstat(descriptor)
            except OSError:
                continue
            if (info.st_dev, info.st_ino) == expected:
                self.real_close(descriptor)


def _reader_probe(source, scenario, primary_name="OSError", target="source", cleanup_name="OSError"):
    import resource

    encrypt = _load_encrypt(source)
    check = unittest.TestCase()
    descriptors = _Descriptors(check)
    real_fdopen = os.fdopen
    primary = _failure(primary_name, "reader construction rejected")
    with tempfile.TemporaryDirectory(prefix="p06-reader-host-only-") as temporary:
        directory = Path(temporary)
        raw = b"host-only verified encryption input\n" * 257
        path = directory / "input"
        path.write_bytes(raw)
        source_info, parent_info = path.stat(), directory.stat()
        source_id = (source_info.st_dev, source_info.st_ino)
        parent_id = (parent_info.st_dev, parent_info.st_ino)
        expected_digest = hashlib.sha256(raw).hexdigest()
        entry = encrypt._Entry(path.name, False, encrypt._stamp(source_info),
                               len(raw), expected_digest)
        audited = []
        reject = scenario != "normal"

        def audit(event, args):
            if event != "open" or type(args[0]) is not int:
                return
            info = os.fstat(args[0])
            if (info.st_dev, info.st_ino) != source_id:
                return
            audited.append(args[0])
            if reject and scenario in ("audit", "repeated", "cleanup"):
                if scenario == "cleanup":
                    wanted = source_id if target == "source" else parent_id
                    descriptors.fail_fd = next(fd for fd, identity in reversed(descriptors.opened)
                                               if identity == wanted)
                    descriptors.failure = _failure(cleanup_name, "reader cleanup rejected")
                raise primary

        def fdopen(*args, **kwargs):
            stream = real_fdopen(*args, **kwargs)
            if reject and scenario == "wrapper":
                # The real wrapper consumes only descriptors it actually owns.
                stream.close()
                raise primary
            return stream

        # Audit hooks and descriptor limits are confined to this child process.
        sys.addaudithook(audit)
        try:
            attempts = 1
            if scenario == "repeated":
                soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
                budget = 64 if soft == resource.RLIM_INFINITY else min(soft, 64)
                resource.setrlimit(resource.RLIMIT_NOFILE, (budget, hard))
                attempts = 2 * budget
            with mock.patch.object(encrypt.os, "open", side_effect=descriptors.open), \
                    mock.patch.object(encrypt.os, "close", side_effect=descriptors.close), \
                    mock.patch.object(encrypt.os, "fdopen", side_effect=fdopen):
                if reject:
                    for _ in range(attempts):
                        with check.assertRaises(BaseException) as caught:
                            encrypt._VerifiedReader(directory, entry, time.monotonic() + 10)
                        check.assertIs(caught.exception, primary)
                    check.assertEqual(len(audited), attempts)
                    descriptors.assert_released()
                reject = False
                descriptors.failure = None
                reader = encrypt._VerifiedReader(directory, entry, time.monotonic() + 10)
                try:
                    pieces = []
                    while body := reader.read(137):
                        pieces.append(body)
                    check.assertEqual(b"".join(pieces), raw)
                    check.assertEqual(reader.verify(), expected_digest)
                finally:
                    reader.close()
                check.assertEqual(len(audited), (attempts if scenario != "normal" else 0) + 1)
                descriptors.assert_released()
        finally:
            reject = False
            descriptors.cleanup()
    print("reader ownership verified")


def _scope_probe(source, scope, operation, primary_name, target, cleanup_name):
    encrypt = _load_encrypt(source)
    check = unittest.TestCase()
    descriptors = _Descriptors(check)
    primary = _failure(primary_name, "reader body rejected")
    secondary = _failure(cleanup_name, "reader close rejected")
    real_fdopen = os.fdopen
    real_read, real_verify = encrypt._VerifiedReader.read, encrypt._VerifiedReader.verify
    active = active_stream = tar_reader = None
    stream_closes = []

    class Stream:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def close(self):
            self.stream.close()
            if active_stream is self and target == "stream":
                stream_closes.append(self)
                raise secondary

    def fdopen(*args, **kwargs):
        stream = real_fdopen(*args, **kwargs)
        info = os.fstat(stream.fileno())
        return Stream(stream) if (info.st_dev, info.st_ino) == source_id else stream

    def selected(reader):
        return reader.entry.name == selected_name and (scope == "inventory" or reader is tar_reader)

    def activate(reader):
        nonlocal active, active_stream
        active, active_stream = reader, reader.stream
        if target == "parent":
            descriptors.fail_fd, descriptors.failure = reader.parent, secondary

    def read(reader, *args, **kwargs):
        if selected(reader) and operation == "read":
            activate(reader)
            raise primary
        return real_read(reader, *args, **kwargs)

    def verify(reader):
        if selected(reader) and operation == "verify":
            activate(reader)
            raise primary
        result = real_verify(reader)
        if selected(reader) and operation == "complete":
            activate(reader)
        return result

    real_addfile = encrypt.tarfile.TarFile.addfile

    def addfile(archive, info, fileobj=None):
        nonlocal tar_reader
        if isinstance(fileobj, encrypt._VerifiedReader) and fileobj.entry.name == selected_name:
            tar_reader = fileobj
        return real_addfile(archive, info, fileobj)

    sys.path.insert(0, str(ROOT / "ci/project"))
    from test_p06_qualified_warm_encrypt import EncryptedRetentionTests

    fixture = EncryptedRetentionTests()
    fixture.setUp()
    selected_name = "private.raw"
    source_info = (fixture.source / selected_name).stat()
    source_id = (source_info.st_dev, source_info.st_ino)
    before = fixture.source_bytes()
    try:
        with mock.patch.object(encrypt.os, "open", side_effect=descriptors.open), \
                mock.patch.object(encrypt.os, "close", side_effect=descriptors.close), \
                mock.patch.object(encrypt.os, "fdopen", side_effect=fdopen), \
                mock.patch.object(encrypt._VerifiedReader, "read", read), \
                mock.patch.object(encrypt._VerifiedReader, "verify", verify), \
                mock.patch.object(encrypt.tarfile.TarFile, "addfile", addfile):
            with check.assertRaises(BaseException) as caught:
                if scope == "inventory":
                    encrypt._inventory(fixture.source, time.monotonic() + 10)
                else:
                    fixture.run_encrypt()
            check.assertIs(caught.exception, secondary if operation == "complete" else primary)
            check.assertIsNotNone(active)
            if target == "stream":
                check.assertEqual(len(stream_closes), 1)
            descriptors.assert_released()
            # Repeated close cannot act on a descriptor that cleanup already released.
            for descriptor, _ in descriptors.opened:
                if descriptor in descriptors.reused:
                    continue
                replacement = descriptors.real_open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
                if replacement != descriptor:
                    os.dup2(replacement, descriptor, inheritable=False)
                    descriptors.real_close(replacement)
                info = os.fstat(descriptor)
                descriptors.reused[descriptor] = (info.st_dev, info.st_ino)
            active.close()
            descriptors.assert_released()
        check.assertEqual(fixture.source_bytes(), before)
        if scope == "tar":
            fixture.assert_failed_public()
    finally:
        descriptors.cleanup()
        fixture.doCleanups()
    print("reader ownership verified")


class EncryptionReaderOwnershipTests(unittest.TestCase):
    def probe(self, *arguments):
        completed = subprocess.run(
            [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--probe",
             str(SOURCE), *arguments],
            capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(completed.stdout, "reader ownership verified\n")

    def test_fdopen_audit_rejection_closes_source_and_parents(self):
        for primary in ("OSError", "KeyboardInterrupt"):
            with self.subTest(primary=primary):
                self.probe("reader", "audit", primary)

    def test_failed_fdopen_wrapper_releases_owned_descriptors(self):
        for primary in ("OSError", "KeyboardInterrupt"):
            with self.subTest(primary=primary):
                self.probe("reader", "wrapper", primary)

    def test_repeated_audit_rejection_does_not_exhaust_descriptors(self):
        self.probe("reader", "repeated")

    def test_constructor_cleanup_preserves_primary_and_reused_descriptors(self):
        for primary in ("OSError", "KeyboardInterrupt"):
            for target in ("source", "parent"):
                for cleanup in ("OSError", "KeyboardInterrupt"):
                    with self.subTest(primary=primary, target=target, cleanup=cleanup):
                        self.probe("reader", "cleanup", primary, target, cleanup)

    def test_normal_read_and_verify_release_all_owned_descriptors(self):
        self.probe("reader", "normal")

    def test_inventory_primary_error_survives_consuming_close_failure(self):
        self._scope_failures("inventory")

    def test_tar_primary_error_survives_consuming_close_failure(self):
        self._scope_failures("tar")

    def _scope_failures(self, scope):
        for operation in ("read", "verify"):
            for primary in ("OSError", "KeyboardInterrupt"):
                for target in ("stream", "parent"):
                    for cleanup in ("OSError", "KeyboardInterrupt"):
                        with self.subTest(operation=operation, primary=primary,
                                          target=target, cleanup=cleanup):
                            self.probe("scope", scope, operation, primary, target, cleanup)

    def test_completed_inventory_and_tar_still_report_close_failure(self):
        for scope in ("inventory", "tar"):
            for target in ("stream", "parent"):
                for cleanup in ("OSError", "KeyboardInterrupt"):
                    with self.subTest(scope=scope, target=target, cleanup=cleanup):
                        self.probe("scope", scope, "complete", "OSError", target, cleanup)


if __name__ == "__main__":
    if len(sys.argv) > 3 and sys.argv[1] == "--probe":
        if sys.argv[3] == "reader":
            _reader_probe(Path(sys.argv[2]), *sys.argv[4:])
        elif sys.argv[3] == "scope":
            _scope_probe(Path(sys.argv[2]), *sys.argv[4:])
        else:
            raise ValueError(sys.argv[3])
    else:
        unittest.main()
