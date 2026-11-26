# SPDX-License-Identifier: Apache-2.0
"""Checkpoint publication preserves foreign entries and releases owned descriptors."""

import errno
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

import p02_matrix as matrix


PREVIOUS = b'{"previous": true}\n'
FOREIGN = b"unrelated writer\n"


def identity(status):
    return status.st_dev, status.st_ino


class CheckpointOwnershipTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="checkpoint-ownership-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def checkpoint(self, name):
        directory = self.root / name
        directory.mkdir()
        path = directory / "report.json"
        path.write_bytes(PREVIOUS)
        return path, directory / "report.json.tmp"

    def foreign_entry(self, directory, kind):
        foreign = directory / "foreign"
        if kind == "regular":
            foreign.write_bytes(FOREIGN)
        else:
            target = directory / "symlink-target"
            target.write_bytes(FOREIGN)
            foreign.symlink_to(target.name)
        return foreign, identity(foreign.lstat())

    def assert_foreign(self, path, kind, expected_identity):
        self.assertEqual(identity(path.lstat()), expected_identity)
        self.assertEqual(path.is_symlink(), kind == "symlink")
        self.assertEqual(path.read_bytes(), FOREIGN)
        if kind == "symlink":
            self.assertEqual(path.readlink(), Path("symlink-target"))

    def assert_closed(self, descriptor):
        with self.assertRaises(OSError) as raised:
            os.fstat(descriptor)
        self.assertEqual(raised.exception.errno, errno.EBADF)

    def test_foreign_entry_before_publication_is_preserved(self):
        actual_fsync = os.fsync
        for kind in ("regular", "symlink"):
            with self.subTest(kind=kind):
                path, temporary = self.checkpoint(kind)
                foreign, foreign_identity = self.foreign_entry(path.parent, kind)
                previous_identity = identity(path.stat())

                def replace_temporary(descriptor):
                    actual_fsync(descriptor)
                    self.assertNotEqual(identity(os.fstat(descriptor)), foreign_identity)
                    os.replace(foreign, temporary)

                with mock.patch.object(matrix.os, "fsync", side_effect=replace_temporary):
                    with self.assertRaisesRegex(ValueError, "temporary ownership changed"):
                        matrix._write_json(path, {"next": True})

                self.assertEqual(path.read_bytes(), PREVIOUS)
                self.assertEqual(identity(path.stat()), previous_identity)
                self.assert_foreign(temporary, kind, foreign_identity)

    def test_foreign_entry_during_failure_cleanup_is_preserved(self):
        actual_stat = os.stat
        for kind in ("regular", "symlink"):
            for error_type in (OSError, KeyboardInterrupt):
                with self.subTest(kind=kind, error=error_type.__name__):
                    path, temporary = self.checkpoint(kind + error_type.__name__)
                    foreign, foreign_identity = self.foreign_entry(path.parent, kind)
                    original = error_type("checkpoint sync failed")
                    observed = {}

                    def fail_sync(descriptor):
                        observed["descriptor"] = descriptor
                        observed["owned"] = identity(os.fstat(descriptor))
                        raise original

                    def replace_during_cleanup(name, *, dir_fd, follow_symlinks):
                        self.assertEqual(name, temporary.name)
                        self.assertFalse(follow_symlinks)
                        self.assertEqual(identity(os.fstat(observed["descriptor"])),
                                         observed["owned"])
                        os.replace(foreign, temporary)
                        observed["replaced"] = True
                        return actual_stat(name, dir_fd=dir_fd,
                                           follow_symlinks=follow_symlinks)

                    with mock.patch.object(matrix.os, "fsync", side_effect=fail_sync), \
                            mock.patch.object(matrix.os, "stat",
                                              side_effect=replace_during_cleanup):
                        with self.assertRaises(error_type) as raised:
                            matrix._write_json(path, {"next": True})

                    self.assertIs(raised.exception, original)
                    self.assertTrue(observed.get("replaced"))
                    self.assertEqual(path.read_bytes(), PREVIOUS)
                    self.assert_foreign(temporary, kind, foreign_identity)
                    self.assert_closed(observed["descriptor"])

    def test_renamed_directory_cleanup_uses_opened_directory(self):
        for replacement_kind in ("directory", "symlink"):
            for error_type in (OSError, KeyboardInterrupt):
                with self.subTest(replacement=replacement_kind, error=error_type.__name__):
                    name = replacement_kind + error_type.__name__
                    path, temporary = self.checkpoint(name)
                    moved = self.root / (name + "-moved")
                    original = error_type("checkpoint sync failed")
                    observed = {}

                    def move_directory_and_fail(descriptor):
                        path.parent.rename(moved)
                        if replacement_kind == "directory":
                            path.parent.mkdir()
                        else:
                            replacement = self.root / (name + "-replacement")
                            replacement.mkdir()
                            path.parent.symlink_to(replacement, target_is_directory=True)
                        path.write_bytes(FOREIGN)
                        temporary.write_bytes(FOREIGN)
                        observed["foreign"] = identity(temporary.stat())
                        raise original

                    with mock.patch.object(matrix.os, "fsync",
                                           side_effect=move_directory_and_fail):
                        with self.assertRaises(error_type) as raised:
                            matrix._write_json(path, {"next": True})

                    self.assertIs(raised.exception, original)
                    self.assertEqual((moved / path.name).read_bytes(), PREVIOUS)
                    self.assertFalse((moved / temporary.name).exists())
                    self.assertEqual(path.read_bytes(), FOREIGN)
                    self.assertEqual(temporary.read_bytes(), FOREIGN)
                    self.assertEqual(identity(temporary.stat()), observed["foreign"])

    def test_fdopen_failure_releases_owned_descriptors(self):
        actual_open, actual_close = os.open, os.close
        for error_type in (OSError, KeyboardInterrupt):
            with self.subTest(error=error_type.__name__):
                path, temporary = self.checkpoint(error_type.__name__)
                original = error_type("stream creation failed")
                opened = []

                def record_open(*args, **kwargs):
                    descriptor = actual_open(*args, **kwargs)
                    opened.append((descriptor, identity(os.fstat(descriptor))))
                    return descriptor

                try:
                    with mock.patch.object(matrix.os, "open", side_effect=record_open), \
                            mock.patch.object(matrix.os, "fdopen", side_effect=original):
                        with self.assertRaises(error_type) as raised:
                            matrix._write_json(path, {"next": True})

                    self.assertIs(raised.exception, original)
                    self.assertEqual(len(opened), 2)
                    for descriptor, _ in opened:
                        self.assert_closed(descriptor)
                    self.assertEqual(path.read_bytes(), PREVIOUS)
                    self.assertFalse(temporary.exists())
                finally:
                    for descriptor, owned_identity in opened:
                        try:
                            if identity(os.fstat(descriptor)) == owned_identity:
                                actual_close(descriptor)
                        except OSError as cleanup_error:
                            if cleanup_error.errno != errno.EBADF:
                                raise

    def test_unlink_failure_preserves_original_exception(self):
        for error_type in (OSError, KeyboardInterrupt):
            for cleanup_type in (OSError, KeyboardInterrupt):
                with self.subTest(error=error_type.__name__, cleanup=cleanup_type.__name__):
                    path, temporary = self.checkpoint(error_type.__name__ + cleanup_type.__name__)
                    original = error_type("checkpoint sync failed")
                    cleanup = cleanup_type("temporary cleanup failed")
                    observed = {}

                    def fail_sync(descriptor):
                        observed["descriptor"] = descriptor
                        observed["owned"] = identity(os.fstat(descriptor))
                        raise original

                    with mock.patch.object(matrix.os, "fsync", side_effect=fail_sync), \
                            mock.patch.object(matrix.os, "unlink", side_effect=cleanup) as unlink:
                        with self.assertRaises(error_type) as raised:
                            matrix._write_json(path, {"next": True})

                    self.assertIs(raised.exception, original)
                    unlink.assert_called_once()
                    self.assertEqual(identity(temporary.stat()), observed["owned"])
                    self.assertEqual(path.read_bytes(), PREVIOUS)
                    self.assert_closed(observed["descriptor"])

    def test_close_failure_preserves_error_and_reused_descriptor(self):
        actual_close = os.close
        for close_directory in (False, True):
            for error_type in (OSError, KeyboardInterrupt):
                with self.subTest(directory=close_directory, error=error_type.__name__):
                    path, temporary = self.checkpoint(str(close_directory) + error_type.__name__)
                    original = error_type("checkpoint sync failed")
                    observed = {}
                    close_calls = []
                    with (path.parent / "sentinel").open("w+b") as sentinel:

                        def fail_close(descriptor):
                            close_calls.append(descriptor)
                            is_directory = stat.S_ISDIR(os.fstat(descriptor).st_mode)
                            actual_close(descriptor)
                            if is_directory == close_directory:
                                os.dup2(sentinel.fileno(), descriptor)
                                observed["reused"] = descriptor
                                raise OSError("descriptor cleanup failed")

                        try:
                            with mock.patch.object(matrix.os, "fsync", side_effect=original), \
                                    mock.patch.object(matrix.os, "close", side_effect=fail_close):
                                with self.assertRaises(error_type) as raised:
                                    matrix._write_json(path, {"next": True})

                            self.assertIs(raised.exception, original)
                            self.assertIn("reused", observed)
                            self.assertEqual(len(close_calls), 2)
                            self.assertEqual(len(set(close_calls)), 2)
                            self.assertEqual(identity(os.fstat(observed["reused"])),
                                             identity(os.fstat(sentinel.fileno())))
                            self.assertEqual(path.read_bytes(), PREVIOUS)
                            self.assertFalse(temporary.exists())
                        finally:
                            if "reused" in observed:
                                try:
                                    actual_close(observed["reused"])
                                except OSError as cleanup_error:
                                    if cleanup_error.errno != errno.EBADF:
                                        raise

    def test_preexisting_temporary_is_not_adopted(self):
        for kind in ("regular", "symlink"):
            with self.subTest(kind=kind):
                path, temporary = self.checkpoint(kind)
                foreign, foreign_identity = self.foreign_entry(path.parent, kind)
                foreign.replace(temporary)

                with self.assertRaises(FileExistsError):
                    matrix._write_json(path, {"next": True})

                self.assertEqual(path.read_bytes(), PREVIOUS)
                self.assert_foreign(temporary, kind, foreign_identity)


if __name__ == "__main__":
    unittest.main()
