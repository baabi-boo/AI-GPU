# SPDX-License-Identifier: Apache-2.0
"""Real-descriptor regressions for governance archive input cleanup."""

from contextlib import ExitStack
import errno
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import governance_replay_archive as reader


def _identity(descriptor):
    info = os.fstat(descriptor)
    return info.st_dev, info.st_ino, info.st_mode


class _InputOwners:
    """Observe real owners and inject one consuming cleanup failure."""

    def __init__(self, fault=None, construction_error=None):
        self.fault = fault
        self.construction_error = construction_error
        self.cleanup_error = OSError(errno.EIO, "injected cleanup failure")
        self.descriptors = {}
        self.identities = {}
        self.attempts = {}
        self.stream = self.original_stream_close = None
        self.witness = self.witness_identity = None
        self.real_close = os.close
        self.real_fdopen = os.fdopen
        self.real_directory = reader._directory
        self.patches = ExitStack()

    def _record(self, owner, descriptor):
        self.descriptors[owner] = descriptor
        self.identities[owner] = _identity(descriptor)

    def _directory(self, path):
        descriptor, identities = self.real_directory(path)
        self._record("parent" if "parent" not in self.descriptors else "fresh", descriptor)
        return descriptor, identities

    def _fdopen(self, descriptor, *args, **kwargs):
        self._record("raw", descriptor)
        if self.construction_error is not None:
            raise self.construction_error
        self.stream = self.real_fdopen(descriptor, *args, **kwargs)
        self.original_stream_close = self.stream.close
        if self.fault == "stream":
            self.stream.close = self._stream_close
        return self.stream

    def _stream_close(self):
        self.attempts["stream"] = self.attempts.get("stream", 0) + 1
        self.original_stream_close()
        raise self.cleanup_error

    def _close(self, descriptor):
        owner = next((name for name, value in self.descriptors.items()
                      if value == descriptor), None)
        if owner is not None:
            self.attempts[owner] = self.attempts.get(owner, 0) + 1
        self.real_close(descriptor)
        if self.fault is not None and owner == self.fault:
            # Reuse the exact consumed number, even if another lower fd is free.
            witness = os.open(os.devnull, os.O_RDONLY | os.O_CLOEXEC)
            if witness != descriptor:
                try:
                    os.dup2(witness, descriptor, inheritable=False)
                finally:
                    self.real_close(witness)
            self.witness = descriptor
            self.witness_identity = _identity(descriptor)
            raise self.cleanup_error

    def __enter__(self):
        self.patches.enter_context(mock.patch.object(reader, "_directory", self._directory))
        self.patches.enter_context(mock.patch.object(reader.os, "fdopen", self._fdopen))
        self.patches.enter_context(mock.patch.object(reader.os, "close", self._close))
        return self

    def __exit__(self, *exc):
        self.patches.close()
        # Failed negative controls must not leak their original owners or witnesses.
        if self.stream is not None:
            self.stream.close = self.original_stream_close
            if not self.stream.closed:
                try:
                    self.original_stream_close()
                except OSError:
                    pass
        for owner, descriptor in self.descriptors.items():
            try:
                if _identity(descriptor) == self.identities[owner]:
                    self.real_close(descriptor)
            except OSError as error:
                if error.errno != errno.EBADF:
                    raise
        if self.witness is not None:
            try:
                if _identity(self.witness) == self.witness_identity:
                    self.real_close(self.witness)
            except OSError as error:
                if error.errno != errno.EBADF:
                    raise

    def assert_drained(self, test):
        for owner, descriptor in self.descriptors.items():
            if descriptor == self.witness:
                test.assertEqual(_identity(descriptor), self.witness_identity,
                                 "cleanup closed a reused descriptor")
            else:
                with test.assertRaises(OSError, msg=f"{owner} descriptor leaked") as caught:
                    os.fstat(descriptor)
                test.assertEqual(caught.exception.errno, errno.EBADF)
        if self.stream is not None:
            test.assertTrue(self.stream.closed)
        if self.fault is not None:
            test.assertEqual(self.attempts.get(self.fault), 1,
                             "a consuming close must be attempted exactly once")
        if self.fault in ("raw", "fresh", "parent"):
            test.assertEqual(self.witness, self.descriptors[self.fault])


class GovernanceArchiveInputOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="governance-input-ownership-")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name).resolve() / "archive.zip"
        # _input validates file identity and bounds; ZIP decoding is a separate layer.
        self.contents = b"a" * 32
        self.path.write_bytes(self.contents)

    def test_fdopen_error_survives_raw_close_error_and_parent_is_closed(self):
        primary = RuntimeError("injected fdopen construction failure")
        with _InputOwners("raw", construction_error=primary) as owners:
            with self.assertRaises(RuntimeError) as caught:
                with reader._input(self.path):
                    self.fail("construction failure must prevent entry")
            self.assertIs(caught.exception, primary)
            owners.assert_drained(self)

    def test_body_error_survives_consuming_stream_close_error(self):
        primary = RuntimeError("injected body failure")
        with _InputOwners("stream") as owners:
            with self.assertRaises(RuntimeError) as caught:
                with reader._input(self.path):
                    raise primary
            self.assertIs(caught.exception, primary)
            owners.assert_drained(self)

    def test_validation_error_survives_fresh_parent_close_error(self):
        with _InputOwners("fresh") as owners:
            with self.assertRaisesRegex(reader.ArchiveError, "archive changed while reading"):
                with reader._input(self.path) as (_, size):
                    self.path.write_bytes(b"b" * (size + 1))
            owners.assert_drained(self)

    def _assert_success_cleanup_failure(self, owner):
        with _InputOwners(owner) as owners:
            with self.assertRaises(OSError) as caught:
                with reader._input(self.path) as (stream, size):
                    self.assertEqual(size, len(self.contents))
                    self.assertEqual(stream.read(), self.contents)
            self.assertIs(caught.exception, owners.cleanup_error)
            self.assertIn("fresh", owners.descriptors,
                          "the successful body must reach identity revalidation")
            owners.assert_drained(self)

    def test_stream_close_error_after_success_drains_descriptors(self):
        self._assert_success_cleanup_failure("stream")

    def test_raw_close_error_after_success_drains_other_descriptors(self):
        self._assert_success_cleanup_failure("raw")

    def test_fresh_parent_close_error_after_success_drains_other_descriptors(self):
        self._assert_success_cleanup_failure("fresh")

    def test_parent_close_error_after_success_preserves_reused_descriptor(self):
        self._assert_success_cleanup_failure("parent")

    def test_unchanged_input_reads_normally_and_closes_descriptors(self):
        with _InputOwners() as owners:
            with reader._input(self.path) as (stream, size):
                self.assertEqual(size, len(self.contents))
                self.assertEqual(stream.read(), self.contents)
            self.assertEqual(set(owners.descriptors), {"raw", "fresh", "parent"})
            owners.assert_drained(self)

    def test_replaced_input_is_rejected_and_closes_descriptors(self):
        replacement = self.path.with_name("replacement.zip")
        replacement.write_bytes(self.contents)
        with _InputOwners() as owners:
            with self.assertRaisesRegex(reader.ArchiveError, "archive changed while reading"):
                with reader._input(self.path):
                    os.replace(replacement, self.path)
            owners.assert_drained(self)


if __name__ == "__main__":
    unittest.main()
