# SPDX-License-Identifier: Apache-2.0
"""Real-descriptor ownership checks for private pack/encryption directory walks."""

import errno
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import p06_qualified_warm_encrypt as encrypt
import p06_qualified_warm_pack as pack


class DirectoryCleanupReviewTests(unittest.TestCase):
    def _is_open(self, descriptor):
        try:
            os.fstat(descriptor)
            return True
        except OSError as error:
            self.assertEqual(error.errno, errno.EBADF)
            return False

    def _check_parent_close_failure(self, module, cleanup_error=None):
        with tempfile.TemporaryDirectory(prefix="p06-directory-cleanup-") as temporary:
            real_open, real_close = os.open, os.close
            opened, closed = [], []
            unrelated = None
            failure = OSError(errno.EIO, "parent close failed after consuming descriptor")

            def record_open(path, flags, *args, **kwargs):
                descriptor = real_open(path, flags, *args, **kwargs)
                opened.append(descriptor)
                return descriptor

            def fail_close(descriptor):
                nonlocal unrelated
                closed.append(descriptor)
                real_close(descriptor)
                if unrelated is None:
                    # A concurrent opener can reuse the number before close reports EIO.
                    unrelated = real_open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
                    self.assertEqual(unrelated, descriptor)
                    raise failure
                if cleanup_error is not None:
                    raise cleanup_error

            try:
                with mock.patch.object(module.os, "open", side_effect=record_open), \
                        mock.patch.object(module.os, "close", side_effect=fail_close):
                    with self.assertRaises(OSError) as caught:
                        module._directory(Path(temporary).resolve())
                with self.subTest(boundary="original failure survives cleanup"):
                    self.assertIs(caught.exception, failure)
                self.assertEqual(len(opened), 2)
                with self.subTest(boundary="unrelated reused descriptor survives"):
                    self.assertTrue(self._is_open(unrelated))
                    self.assertEqual(closed.count(unrelated), 1)
                with self.subTest(boundary="opened child is released"):
                    self.assertFalse(self._is_open(opened[1]))
                    self.assertEqual(closed.count(opened[1]), 1)
            finally:
                for descriptor in set(opened + [unrelated]):
                    if descriptor is not None and self._is_open(descriptor):
                        real_close(descriptor)

    def test_parent_close_error_preserves_unrelated_fd_and_releases_child(self):
        for module in (pack, encrypt):
            with self.subTest(module=module.__name__):
                self._check_parent_close_failure(module)

    def test_child_cleanup_error_does_not_replace_parent_close_failure(self):
        for module in (pack, encrypt):
            with self.subTest(module=module.__name__):
                self._check_parent_close_failure(
                    module, OSError(errno.ENOSPC, "child cleanup failed"))


if __name__ == "__main__":
    unittest.main()
