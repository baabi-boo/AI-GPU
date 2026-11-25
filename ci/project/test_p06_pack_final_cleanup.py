# SPDX-License-Identifier: Apache-2.0
"""Real-descriptor final-close failures for both PRIVATE packaging APIs."""

import errno
import json
import os
import unittest
from unittest import mock

import p06_qualified_warm_pack as pack
import test_p06_qualified_warm_pack as fixtures


class PackagingFinalCleanupTests(unittest.TestCase):
    setUp = fixtures.PrivatePackagingTests.setUp
    put = fixtures.PrivatePackagingTests.put
    write_json = fixtures.PrivatePackagingTests.write_json
    descriptor = fixtures.PrivatePackagingTests.descriptor
    make_success = fixtures.PrivatePackagingTests.make_success
    arguments = fixtures.PrivatePackagingTests.arguments
    tree_bytes = fixtures.PrivatePackagingTests.tree_bytes

    def _is_open(self, descriptor):
        try:
            os.fstat(descriptor)
            return True
        except OSError as error:
            self.assertEqual(error.errno, errno.EBADF)
            return False

    def _check_final_close_failure(self, action, *, primary=None, caller_except=False):
        suffix = type(primary).__name__ if primary is not None else "success"
        self.output = self.root / (action.__name__ + "-" + suffix + "-" + str(caller_except))
        originals = self.tree_bytes()
        real_open, real_close, real_inventory = os.open, os.close, pack._inventory
        output_fd = output_identity = None
        closed = []
        foreign = real_open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
        foreign_info = os.fstat(foreign)
        foreign_identity = (foreign_info.st_dev, foreign_info.st_ino)
        cleanup_error = OSError(errno.EIO, "final output close failed after consuming descriptor")

        def record_open(path, flags, *args, **kwargs):
            nonlocal output_fd, output_identity
            descriptor = real_open(path, flags, *args, **kwargs)
            if output_fd is None and path == self.output.name and kwargs.get("dir_fd") is not None:
                output_fd = descriptor
                info = os.fstat(descriptor)
                output_identity = (info.st_dev, info.st_ino)
            return descriptor

        def fail_close(descriptor):
            if descriptor != output_fd:
                return real_close(descriptor)
            closed.append(descriptor)
            real_close(descriptor)
            if len(closed) == 1:
                # Force reuse of this exact number even when a lower fd is free.
                # Any retry would close an unrelated, still-live descriptor.
                os.dup2(foreign, descriptor, inheritable=False)
                raise cleanup_error

        def inventory(selections):
            self.assertIsNotNone(output_fd)
            if primary is not None:
                raise primary
            return real_inventory(selections)

        def invoke():
            if caller_except:
                try:
                    raise RuntimeError("unrelated caller failure")
                except RuntimeError:
                    action(**self.arguments())
            else:
                action(**self.arguments())

        try:
            with mock.patch.object(pack.os, "open", side_effect=record_open), \
                    mock.patch.object(pack.os, "close", side_effect=fail_close), \
                    mock.patch.object(pack, "_inventory", side_effect=inventory):
                with self.assertRaises(BaseException) as caught:
                    invoke()
            self.assertIsNotNone(output_fd)
            self.assertEqual(closed, [output_fd])
            self.assertNotEqual(output_identity, foreign_identity)
            self.assertTrue(self._is_open(output_fd))
            replacement = os.fstat(output_fd)
            self.assertEqual((replacement.st_dev, replacement.st_ino), foreign_identity)
            self.assertEqual(self.tree_bytes(), originals)
            if primary is not None:
                failure = json.loads((self.output / pack.FAILURE_NAME).read_bytes())
                self.assertEqual(failure["stage"], "inventory")
                self.assertEqual(failure["error_type"], type(primary).__name__)
                self.assertFalse(failure["packaging_passed"])
                self.assertFalse((self.output / pack.RECEIPT_NAME).exists())
            else:
                receipt = json.loads((self.output / pack.RECEIPT_NAME).read_bytes())
                self.assertTrue(receipt["packaging_passed"])
                self.assertEqual(receipt["partial_attempt"], action is pack.package_partial)
                self.assertTrue(all((self.output / row["filename"]).is_file()
                                    for row in receipt["archives"]))
            self.assertIs(caught.exception, primary if primary is not None else cleanup_error)
        finally:
            if output_fd is not None and self._is_open(output_fd):
                real_close(output_fd)
            real_close(foreign)

    def test_primary_failure_survives_final_output_close_failure(self):
        for action in (pack.package_success, pack.package_partial):
            for error_type in (RuntimeError, KeyboardInterrupt, ValueError):
                with self.subTest(action=action.__name__, primary=error_type.__name__):
                    self._check_final_close_failure(action, primary=error_type("inventory failed"))

    def test_final_output_close_failure_is_fatal_after_success(self):
        for action in (pack.package_success, pack.package_partial):
            with self.subTest(action=action.__name__):
                self._check_final_close_failure(action)

    def test_final_output_close_failure_is_fatal_inside_callers_except(self):
        for action in (pack.package_success, pack.package_partial):
            with self.subTest(action=action.__name__):
                self._check_final_close_failure(action, caller_except=True)


if __name__ == "__main__":
    unittest.main()
