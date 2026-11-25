# SPDX-License-Identifier: Apache-2.0
"""Real-descriptor cleanup when PRIVATE packaging output setup fails."""

import errno
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import p06_qualified_warm_pack as pack


class PackagingSetupCleanupTests(unittest.TestCase):
    def _is_open(self, descriptor):
        try:
            os.fstat(descriptor)
            return True
        except OSError as error:
            self.assertEqual(error.errno, errno.EBADF)
            return False

    def _check_parent_close_failure(self, action, cleanup_error=None):
        with tempfile.TemporaryDirectory(prefix="p06-pack-setup-") as temporary:
            root = Path(temporary).resolve()
            source, workspace, output = (root / name for name in ("source", "workspace", "output"))
            source.mkdir()
            workspace.mkdir()
            real_open, real_close, real_directory = os.open, os.close, pack._directory
            parent_fd = output_fd = unrelated = None
            closed = []
            failure = OSError(errno.EIO, "parent close failed after consuming descriptor")

            def record_directory(path):
                nonlocal parent_fd
                descriptor = real_directory(path)
                if path == output.parent:
                    parent_fd = descriptor
                return descriptor

            def record_open(path, flags, *args, **kwargs):
                nonlocal output_fd
                descriptor = real_open(path, flags, *args, **kwargs)
                if path == output.name and kwargs.get("dir_fd") == parent_fd:
                    output_fd = descriptor
                return descriptor

            def fail_close(descriptor):
                nonlocal unrelated
                if output_fd is not None:
                    closed.append(descriptor)
                real_close(descriptor)
                if descriptor == parent_fd and output_fd is not None and unrelated is None:
                    # A concurrent opener can reuse the number before close reports EIO.
                    unrelated = real_open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
                    self.assertEqual(unrelated, descriptor)
                    raise failure
                if descriptor == output_fd and cleanup_error is not None:
                    raise cleanup_error

            try:
                with mock.patch.object(pack, "_directory", side_effect=record_directory), \
                        mock.patch.object(pack.os, "open", side_effect=record_open), \
                        mock.patch.object(pack.os, "close", side_effect=fail_close), \
                        mock.patch.object(pack, "_inventory") as inventory:
                    with self.assertRaises(OSError) as caught:
                        action(source_dir=source, workspace_dir=workspace,
                               output_dir=output, writers_finished=True)
                self.assertIs(caught.exception, failure)
                inventory.assert_not_called()
                self.assertIsNotNone(output_fd)
                self.assertIsNotNone(unrelated)
                self.assertTrue(self._is_open(unrelated))
                self.assertEqual(closed.count(parent_fd), 1)
                self.assertFalse(self._is_open(output_fd))
                self.assertEqual(closed.count(output_fd), 1)
            finally:
                for descriptor in {parent_fd, output_fd, unrelated}:
                    if descriptor is not None and self._is_open(descriptor):
                        real_close(descriptor)

    def test_parent_close_failure_releases_output_and_preserves_reused_descriptor(self):
        for action in (pack.package_success, pack.package_partial):
            with self.subTest(action=action.__name__):
                self._check_parent_close_failure(action)

    def test_output_cleanup_failure_preserves_parent_close_failure(self):
        for action in (pack.package_success, pack.package_partial):
            for cleanup_error in (OSError(errno.ENOSPC, "output cleanup failed"), KeyboardInterrupt()):
                with self.subTest(action=action.__name__, cleanup_error=type(cleanup_error).__name__):
                    self._check_parent_close_failure(action, cleanup_error)


if __name__ == "__main__":
    unittest.main()
