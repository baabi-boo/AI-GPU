# SPDX-License-Identifier: Apache-2.0
"""Independent ownership check for directory traversal during receipt recovery."""

from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import p06_qualified_warm_control as control
from test_p06_qualified_warm_control import AZURE, BODY, Response


class ControlRecoveryWalkReviewTests(unittest.TestCase):
    @staticmethod
    @contextmanager
    def opener(_value, *, timeout):
        yield Response()

    def test_recovery_walk_close_failure_preserves_unrelated_reused_descriptor(self):
        with tempfile.TemporaryDirectory(prefix="p06-control-final-review-") as temporary:
            output = Path(temporary).resolve() / "intake"
            real_open, real_close = os.open, os.close
            real_output_close = control._PrivateOutput.close
            recovering, injected = False, False
            recovery_opens, recovery_closes = [], []
            unrelated_descriptor = None

            def close_output(value):
                nonlocal recovering
                real_output_close(value)
                recovering = True
                raise OSError(errno.EIO, "synthetic-private-detail " + AZURE)

            def record_open(path, flags, *args, **kwargs):
                descriptor = real_open(path, flags, *args, **kwargs)
                if recovering:
                    recovery_opens.append(descriptor)
                return descriptor

            def fail_recovery_close(descriptor):
                nonlocal injected, unrelated_descriptor
                if recovering:
                    recovery_closes.append(descriptor)
                real_close(descriptor)
                if recovering and not injected:
                    injected = True
                    # Another thread may reuse a descriptor after close consumes it.
                    unrelated_descriptor = real_open("/dev/null", os.O_RDONLY)
                    self.assertEqual(unrelated_descriptor, descriptor)
                    raise OSError(errno.EIO, "synthetic-private-detail " + AZURE)

            def is_open(descriptor):
                try:
                    os.fstat(descriptor)
                    return True
                except OSError as error:
                    self.assertEqual(error.errno, errno.EBADF)
                    return False

            try:
                with mock.patch.object(control, "_reviewed_identity", return_value={
                        "sha256": hashlib.sha256(BODY).hexdigest(), "size_bytes": len(BODY)}), \
                        mock.patch.object(control.os, "fstatvfs", return_value=SimpleNamespace(
                            f_bavail=100 * 1024**3, f_frsize=1)), \
                        mock.patch.dict(os.environ, {control.URL_ENVIRONMENT_VARIABLE: AZURE}), \
                        mock.patch.object(control._PrivateOutput, "close", new=close_output), \
                        mock.patch.object(control.os, "open", side_effect=record_open), \
                        mock.patch.object(control.os, "close", side_effect=fail_recovery_close):
                    with self.assertRaises(control.IntakeError) as caught:
                        control.acquire_control(output, opener=self.opener)

                self.assertTrue(injected)
                self.assertEqual(caught.exception.code, "storage_failed")
                self.assertEqual(str(caught.exception), control._REASONS["storage_failed"])
                self.assertEqual((output / control.ARCHIVE_NAME).read_bytes(), BODY)
                raw = (output / control.RECEIPT_NAME).read_bytes()
                for secret in (b"https:", b"sig=", b"never-retain", b"synthetic-private-detail"):
                    self.assertNotIn(secret, raw)
                self.assertIn(json.loads(raw)["outcome"], ("pass", "fail"))
                with self.subTest(boundary="unrelated descriptor survives"):
                    self.assertTrue(is_open(unrelated_descriptor))
                    self.assertEqual(recovery_closes.count(unrelated_descriptor), 1)
                with self.subTest(boundary="opened recovery children are released"):
                    self.assertEqual([descriptor for descriptor in recovery_opens
                                      if descriptor != unrelated_descriptor and is_open(descriptor)], [])
            finally:
                for descriptor in set(recovery_opens + [unrelated_descriptor]):
                    if descriptor is not None and is_open(descriptor):
                        real_close(descriptor)


if __name__ == "__main__":
    unittest.main()
