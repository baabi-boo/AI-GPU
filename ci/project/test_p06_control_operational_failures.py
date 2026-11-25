# SPDX-License-Identifier: Apache-2.0
"""Synthetic transfer and local-storage closeout failures for private intake."""

from contextlib import contextmanager
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import p06_qualified_warm_control as control
from test_p06_qualified_warm_control import AZURE, BODY, Response


class ControlStorageFailureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-control-failure-")
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name).resolve() / "intake"
        self.enterContext(mock.patch.object(control, "_reviewed_identity", return_value={
            "sha256": hashlib.sha256(BODY).hexdigest(), "size_bytes": len(BODY)}))
        self.enterContext(mock.patch.object(control.os, "fstatvfs", return_value=
            SimpleNamespace(f_bavail=100 * 1024**3, f_frsize=1)))
        self.enterContext(mock.patch.dict(os.environ, {control.URL_ENVIRONMENT_VARIABLE: AZURE}))

    @staticmethod
    @contextmanager
    def opener(_value, *, timeout):
        yield Response()

    def read_receipt(self):
        raw = (self.output / control.RECEIPT_NAME).read_bytes()
        for forbidden in (b"never-retain", b"https:", b"sig=", b"synthetic-private-detail"):
            self.assertNotIn(forbidden, raw)
        return json.loads(raw)

    def is_archive(self, descriptor):
        archive = self.output / control.ARCHIVE_NAME
        return archive.exists() and control._same_inode(os.fstat(descriptor), archive.stat())

    def test_disk_full_reports_storage_failure_and_actual_partial_bytes(self):
        original_write, wrote = os.write, False

        def fail_write(descriptor, body):
            nonlocal wrote
            if self.is_archive(descriptor):
                if wrote:
                    raise OSError(errno.ENOSPC, "synthetic-private-detail " + AZURE)
                wrote = True
                return original_write(descriptor, body[:3])
            return original_write(descriptor, body)

        with mock.patch.object(control.os, "write", side_effect=fail_write):
            report = control.acquire_control(self.output, opener=self.opener)
        self.assertEqual(report["reason_code"], "storage_failed")
        self.assertEqual(report["outcome"], "fail")
        self.assertFalse(report["original_verified"])
        self.assertEqual(report["retained_state"], "partial")
        self.assertEqual(report["retained_original"], {
            "path": control.ARCHIVE_NAME, "size_bytes": 3,
            "sha256": hashlib.sha256(BODY[:3]).hexdigest()})
        self.assertEqual((self.output / control.ARCHIVE_NAME).read_bytes(), BODY[:3])
        self.assertEqual(self.read_receipt(), report)

    def test_archive_sync_failure_is_local_storage_failure(self):
        original_fsync = os.fsync

        def fail_archive_sync(descriptor):
            if self.is_archive(descriptor):
                raise OSError(errno.EIO, "synthetic-private-detail " + AZURE)
            return original_fsync(descriptor)

        with mock.patch.object(control.os, "fsync", side_effect=fail_archive_sync):
            report = control.acquire_control(self.output, opener=self.opener)
        self.assertEqual(report["reason_code"], "storage_failed")
        self.assertTrue(report["retention_identity_unavailable"])
        self.assertFalse(report["original_verified"])
        self.assertEqual((self.output / control.ARCHIVE_NAME).read_bytes(), BODY)
        self.assertEqual(self.read_receipt(), report)

    def test_failed_receipt_sync_cannot_leave_a_success_receipt(self):
        for failure in ("file", "directory"):
            with self.subTest(failure=failure):
                self.output = self.output.parent / failure
                os.environ[control.URL_ENVIRONMENT_VARIABLE] = AZURE
                original_fsync = os.fsync

                def fail_receipt_sync(descriptor):
                    directory = stat.S_ISDIR(os.fstat(descriptor).st_mode)
                    if (failure == "directory" and directory) or (
                            failure == "file" and not directory and not self.is_archive(descriptor)):
                        raise OSError(errno.EIO, "synthetic-private-detail " + AZURE)
                    return original_fsync(descriptor)

                with mock.patch.object(control.os, "fsync", side_effect=fail_receipt_sync):
                    with self.assertRaises(control.IntakeError) as raised:
                        control.acquire_control(self.output, opener=self.opener)
                self.assertEqual(raised.exception.code, "receipt_failed")
                report = self.read_receipt()
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(report["reason_code"], "receipt_failed")
                self.assertFalse(report["original_verified"])
                self.assertEqual(report["retained_state"], "partial")
                self.assertEqual((self.output / control.ARCHIVE_NAME).read_bytes(), BODY)

    def test_failed_receipt_cleanup_does_not_modify_a_replacement(self):
        original_status = control._PrivateOutput.file_status
        sentinel = b"unowned replacement must remain unchanged"
        owned_receipt = self.output / "owned-receipt.json"

        def replace_receipt(output, descriptor, name):
            if name == control.RECEIPT_NAME and os.fstat(descriptor).st_size:
                (self.output / name).rename(owned_receipt)
                (self.output / name).write_bytes(sentinel)
            return original_status(output, descriptor, name)

        with mock.patch.object(control._PrivateOutput, "file_status", new=replace_receipt):
            with self.assertRaises(control.IntakeError) as raised:
                control.acquire_control(self.output, opener=self.opener)
        self.assertEqual(raised.exception.code, "receipt_failed")
        self.assertEqual((self.output / control.RECEIPT_NAME).read_bytes(), sentinel)
        self.assertEqual((self.output / control.ARCHIVE_NAME).read_bytes(), BODY)
        report = json.loads(owned_receipt.read_bytes())
        self.assertEqual(report["outcome"], "fail")
        self.assertFalse(report["original_verified"])


class ControlResponseCloseTests(unittest.TestCase):
    def test_unread_connection_close_responses_are_closed_on_failure(self):
        class Socket:
            def __init__(self, status):
                self.body = io.BytesIO((f"HTTP/1.1 {status} Synthetic\r\nContent-Length: 5\r\n"
                    "Connection: close\r\n\r\nerror").encode("ascii"))

            def makefile(self, _mode):
                return self.body

            def sendall(self, _body):
                pass

            def close(self):
                pass

        for failure in (control.IntakeError("response_rejected"), KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__):
                socket = Socket(403 if isinstance(failure, control.IntakeError) else 200)

                def connect(connection):
                    connection.sock = socket

                with mock.patch.object(control.http.client.HTTPSConnection, "connect", new=connect):
                    with self.assertRaises(type(failure)):
                        with control._open_https(AZURE, timeout=20) as response:
                            raise failure
                self.assertTrue(response.isclosed())
                self.assertTrue(socket.body.closed)

    def test_response_close_failure_still_closes_connection(self):
        connection = mock.Mock()
        connection.getresponse.return_value.close.side_effect = OSError(errno.EIO, "synthetic-private-detail")
        with mock.patch.object(control.http.client, "HTTPSConnection", return_value=connection):
            with self.assertRaises(OSError):
                with control._open_https(AZURE, timeout=20):
                    pass
        connection.getresponse.return_value.close.assert_called_once()
        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
