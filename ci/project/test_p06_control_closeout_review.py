# SPDX-License-Identifier: Apache-2.0
"""Independent closeout boundaries for the exact private control intake."""

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


class ControlCloseoutReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-control-closeout-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.output = self.root / "intake"
        self.enterContext(mock.patch.object(control, "_reviewed_identity", return_value={
            "sha256": hashlib.sha256(BODY).hexdigest(), "size_bytes": len(BODY)}))
        self.enterContext(mock.patch.object(control.os, "fstatvfs", return_value=
            SimpleNamespace(f_bavail=100 * 1024**3, f_frsize=1)))
        self.enterContext(mock.patch.dict(os.environ, {control.URL_ENVIRONMENT_VARIABLE: AZURE}))

    def receipt(self, path=None):
        body = (path or self.output / control.RECEIPT_NAME).read_bytes()
        for secret in (b"https:", b"sig=", b"never-retain", b"synthetic-private-detail"):
            self.assertNotIn(secret, body)
        return json.loads(body)

    def is_named_inode(self, descriptor, name):
        path = self.output / name
        return path.exists() and control._same_inode(os.fstat(descriptor), path.stat())

    def test_transport_cleanup_preserves_first_storage_failure(self):
        for failure in ("response", "connection", "both"):
            with self.subTest(failure=failure):
                self.output = self.root / failure
                os.environ[control.URL_ENVIRONMENT_VARIABLE] = AZURE
                response = Response()
                response.close = mock.Mock()
                connection = mock.Mock()
                connection.getresponse.return_value = response
                if failure in ("response", "both"):
                    response.close.side_effect = OSError(errno.EIO, "synthetic-private-detail " + AZURE)
                if failure in ("connection", "both"):
                    connection.close.side_effect = OSError(errno.EIO, "synthetic-private-detail " + AZURE)
                original_write, wrote = os.write, False

                def fail_write(descriptor, body):
                    nonlocal wrote
                    if self.is_named_inode(descriptor, control.ARCHIVE_NAME):
                        if wrote:
                            raise OSError(errno.ENOSPC, "synthetic-private-detail " + AZURE)
                        wrote = True
                        return original_write(descriptor, body[:3])
                    return original_write(descriptor, body)

                with mock.patch.object(control.http.client, "HTTPSConnection", return_value=connection), \
                        mock.patch.object(control.os, "write", side_effect=fail_write):
                    report = control.acquire_control(self.output)
                response.close.assert_called_once()
                connection.close.assert_called_once()
                self.assertEqual((self.output / control.ARCHIVE_NAME).read_bytes(), BODY[:3])
                self.assertEqual(self.receipt(), report)
                self.assertEqual(report["reason_code"], "storage_failed")
                self.assertEqual(report["outcome"], "fail")
                self.assertFalse(report["original_verified"])
                self.assertEqual(report["retained_original"], {
                    "path": control.ARCHIVE_NAME, "size_bytes": 3,
                    "sha256": hashlib.sha256(BODY[:3]).hexdigest()})

    def test_transport_cleanup_preserves_partial_interruption(self):
        def interrupt(response):
            if response.position:
                raise KeyboardInterrupt("synthetic-private-detail " + AZURE)

        response = Response(read_hook=interrupt)
        response.close = mock.Mock(side_effect=OSError(errno.EIO, "synthetic-private-detail " + AZURE))
        connection = mock.Mock()
        connection.getresponse.return_value = response
        connection.close.side_effect = OSError(errno.EIO, "synthetic-private-detail " + AZURE)
        with mock.patch.object(control.http.client, "HTTPSConnection", return_value=connection):
            report = control.acquire_control(self.output)
        response.close.assert_called_once()
        connection.close.assert_called_once()
        self.assertEqual((self.output / control.ARCHIVE_NAME).read_bytes(), BODY[:7])
        self.assertEqual(self.receipt(), report)
        self.assertEqual(report["reason_code"], "interrupted")
        self.assertEqual(report["outcome"], "fail")
        self.assertFalse(report["original_verified"])

    def test_receipt_close_failure_invalidates_owned_success(self):
        connection = mock.Mock()
        connection.getresponse.return_value = Response()
        original_close, failed = os.close, False

        def fail_receipt_close(descriptor):
            nonlocal failed
            receipt = self.is_named_inode(descriptor, control.RECEIPT_NAME)
            original_close(descriptor)
            if receipt and not failed:
                failed = True
                raise OSError(errno.EIO, "synthetic-private-detail " + AZURE)

        with mock.patch.object(control.http.client, "HTTPSConnection", return_value=connection), \
                mock.patch.object(control.os, "close", side_effect=fail_receipt_close):
            with self.assertRaises(Exception) as caught:
                control.acquire_control(self.output)
        self.assertTrue(failed)
        self.assertEqual((self.output / control.ARCHIVE_NAME).read_bytes(), BODY)
        report = self.receipt()
        self.assertEqual(report["outcome"], "fail")
        self.assertFalse(report["original_verified"])
        self.assertEqual(report["reason_code"], "receipt_failed")
        self.assertIsInstance(caught.exception, control.IntakeError)
        self.assertEqual(caught.exception.code, "receipt_failed")
        self.assertEqual(str(caught.exception), control._REASONS["receipt_failed"])

    def test_receipt_symlink_replacement_cannot_truncate_last_original(self):
        connection = mock.Mock()
        connection.getresponse.return_value = Response()
        original_status = control._PrivateOutput.file_status
        owned_receipt = self.output / "owned-receipt.json"
        replaced = False

        def replace_receipt(output, descriptor, name):
            nonlocal replaced
            if name == control.RECEIPT_NAME and os.fstat(descriptor).st_size and not replaced:
                replaced = True
                (self.output / name).rename(owned_receipt)
                (self.output / name).symlink_to(control.ARCHIVE_NAME)
            return original_status(output, descriptor, name)

        with mock.patch.object(control.http.client, "HTTPSConnection", return_value=connection), \
                mock.patch.object(control._PrivateOutput, "file_status", new=replace_receipt):
            with self.assertRaises(control.IntakeError) as caught:
                control.acquire_control(self.output)
        self.assertEqual(caught.exception.code, "receipt_failed")
        self.assertTrue((self.output / control.RECEIPT_NAME).is_symlink())
        self.assertEqual(os.readlink(self.output / control.RECEIPT_NAME), control.ARCHIVE_NAME)
        self.assertEqual((self.output / control.ARCHIVE_NAME).read_bytes(), BODY)
        report = self.receipt(owned_receipt)
        self.assertEqual(report["outcome"], "fail")
        self.assertFalse(report["original_verified"])


if __name__ == "__main__":
    unittest.main()
