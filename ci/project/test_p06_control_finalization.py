# SPDX-License-Identifier: Apache-2.0
"""Final archive and directory close failures retain a failed private intake."""

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


class ControlFinalizationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-control-finalization-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.output = self.root / "intake"
        self.enterContext(mock.patch.object(control, "_reviewed_identity", return_value={
            "sha256": hashlib.sha256(BODY).hexdigest(), "size_bytes": len(BODY)}))
        self.enterContext(mock.patch.object(control.os, "fstatvfs", return_value=
            SimpleNamespace(f_bavail=100 * 1024**3, f_frsize=1)))
        self.enterContext(mock.patch.dict(os.environ, {control.URL_ENVIRONMENT_VARIABLE: AZURE}))

    @staticmethod
    @contextmanager
    def opener(_value, *, timeout):
        yield Response()

    def receipt(self, path=None):
        body = (path or self.output / control.RECEIPT_NAME).read_bytes()
        for secret in (b"https:", b"sig=", b"never-retain", b"synthetic-private-detail"):
            self.assertNotIn(secret, body)
        return json.loads(body)

    @contextmanager
    def close_failures(self, *, archive=False, directory=False, after_directory=None):
        real_close = os.close
        real_create = control._PrivateOutput.create
        real_output_close = control._PrivateOutput.close
        observed = SimpleNamespace(archive_closes=0, directory_closes=0, output=None,
                                   archive_fd=None, directory_fd=None)

        def create(output, name):
            observed.output = output
            observed.directory_fd = output.descriptor
            descriptor = real_create(output, name)
            if name == control.ARCHIVE_NAME:
                observed.archive_fd = descriptor
            return descriptor

        def close(descriptor):
            path = self.output / control.ARCHIVE_NAME
            is_archive = (path.exists()
                          and control._same_inode(os.fstat(descriptor), path.stat()))
            real_close(descriptor)
            if is_archive:
                observed.archive_closes += 1
                if archive:
                    raise OSError(errno.EIO, "synthetic-private-detail " + AZURE)

        def close_output(output):
            observed.directory_closes += 1
            real_output_close(output)
            if after_directory is not None:
                after_directory()
            if directory:
                raise OSError(errno.EIO, "synthetic-private-detail " + AZURE)

        try:
            with mock.patch.object(control._PrivateOutput, "create", new=create), \
                    mock.patch.object(control._PrivateOutput, "close", new=close_output), \
                    mock.patch.object(control.os, "close", side_effect=close):
                yield observed
        finally:
            # A failing implementation must not leak its live directory into other tests.
            if observed.output is not None and observed.output.descriptor is not None:
                descriptor, observed.output.descriptor = observed.output.descriptor, None
                real_close(descriptor)

    def assert_sanitized_failure(self, error, code):
        self.assertIsInstance(error, control.IntakeError)
        self.assertEqual(error.code, code)
        self.assertEqual(str(error), control._REASONS[code])

    def assert_released(self, *descriptors):
        for descriptor in descriptors:
            with self.assertRaises(OSError) as caught:
                os.fstat(descriptor)
            self.assertEqual(caught.exception.errno, errno.EBADF)

    def test_archive_close_after_release_invalidates_success_and_closes_directory(self):
        with self.close_failures(archive=True) as observed:
            with self.assertRaises(Exception) as caught:
                control.acquire_control(self.output, opener=self.opener)
            self.assertEqual(observed.archive_closes, 1)
            self.assertEqual(observed.directory_closes, 1)
            self.assertIsNone(observed.output.descriptor)
            self.assert_released(observed.archive_fd, observed.directory_fd)
        self.assert_sanitized_failure(caught.exception, "storage_failed")
        report = self.receipt()
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual(report["reason_code"], "storage_failed")
        self.assertFalse(report["original_verified"])
        self.assertEqual((self.output / control.ARCHIVE_NAME).read_bytes(), BODY)

    def test_directory_close_after_release_invalidates_owned_success(self):
        with self.close_failures(directory=True) as observed:
            with self.assertRaises(Exception) as caught:
                control.acquire_control(self.output, opener=self.opener)
            self.assertEqual(observed.archive_closes, 1)
            self.assertEqual(observed.directory_closes, 1)
            self.assertIsNone(observed.output.descriptor)
            self.assert_released(observed.archive_fd, observed.directory_fd)
        report = self.receipt()
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual(report["reason_code"], "storage_failed")
        self.assertFalse(report["original_verified"])
        self.assert_sanitized_failure(caught.exception, "storage_failed")
        self.assertEqual((self.output / control.ARCHIVE_NAME).read_bytes(), BODY)

    def test_primary_receipt_failure_survives_directory_close_failure(self):
        real_fsync = os.fsync

        def fail_receipt_sync(descriptor):
            receipt = self.output / control.RECEIPT_NAME
            if receipt.exists() and control._same_inode(os.fstat(descriptor), receipt.stat()):
                raise OSError(errno.EIO, "synthetic-private-detail " + AZURE)
            real_fsync(descriptor)

        with self.close_failures(directory=True) as observed, \
                mock.patch.object(control.os, "fsync", side_effect=fail_receipt_sync):
            with self.assertRaises(Exception) as caught:
                control.acquire_control(self.output, opener=self.opener)
            self.assertEqual(observed.directory_closes, 1)
        self.assert_sanitized_failure(caught.exception, "receipt_failed")
        self.assertEqual(self.receipt()["reason_code"], "receipt_failed")
        self.assertEqual((self.output / control.ARCHIVE_NAME).read_bytes(), BODY)

    def test_primary_interruption_survives_both_outer_close_failures(self):
        @contextmanager
        def interrupted(_value, *, timeout):
            def interrupt(response):
                if response.position:
                    raise KeyboardInterrupt("synthetic-private-detail " + AZURE)
            yield Response(read_hook=interrupt)

        with self.close_failures(archive=True, directory=True) as observed:
            with self.assertRaises(Exception) as caught:
                control.acquire_control(self.output, opener=interrupted)
            self.assertEqual(observed.archive_closes, 1)
            self.assertEqual(observed.directory_closes, 1)
        self.assert_sanitized_failure(caught.exception, "interrupted")
        report = self.receipt()
        self.assertEqual(report["reason_code"], "interrupted")
        self.assertEqual(report["outcome"], "fail")
        self.assertFalse(report["original_verified"])
        self.assertEqual((self.output / control.ARCHIVE_NAME).read_bytes(), BODY[:7])

    def test_post_release_receipt_replacements_remain_unchanged(self):
        for kind in ("regular", "symlink", "archive_hardlink"):
            with self.subTest(kind=kind):
                self.output = self.root / kind
                os.environ[control.URL_ENVIRONMENT_VARIABLE] = AZURE
                owned_receipt = self.output / "owned-receipt.json"
                receipt = self.output / control.RECEIPT_NAME
                archive = self.output / control.ARCHIVE_NAME
                sentinel = b"unowned replacement"

                def replace_receipt():
                    receipt.rename(owned_receipt)
                    if kind == "regular":
                        receipt.write_bytes(sentinel)
                        receipt.chmod(0o600)
                    elif kind == "symlink":
                        receipt.symlink_to(control.ARCHIVE_NAME)
                    else:
                        os.link(archive, receipt)

                with self.close_failures(directory=True, after_directory=replace_receipt):
                    with self.assertRaises(Exception) as caught:
                        control.acquire_control(self.output, opener=self.opener)
                self.assert_sanitized_failure(caught.exception, "storage_failed")
                self.assertEqual(archive.read_bytes(), BODY)
                self.assertEqual(receipt.read_bytes(), sentinel if kind == "regular" else BODY)
                if kind == "symlink":
                    self.assertTrue(receipt.is_symlink())
                    self.assertEqual(os.readlink(receipt), control.ARCHIVE_NAME)
                # No descriptor remains for the renamed owned inode; do not search for it.
                self.assertEqual(self.receipt(owned_receipt)["outcome"], "pass")

    def test_post_release_directory_replacement_is_not_used_for_repair(self):
        owned_output = self.root / "owned-output"
        sentinel = b"unowned directory receipt"

        def replace_directory():
            self.output.rename(owned_output)
            self.output.mkdir(mode=0o700)
            receipt = self.output / control.RECEIPT_NAME
            receipt.write_bytes(sentinel)
            receipt.chmod(0o600)

        with self.close_failures(directory=True, after_directory=replace_directory):
            with self.assertRaises(Exception) as caught:
                control.acquire_control(self.output, opener=self.opener)
        self.assert_sanitized_failure(caught.exception, "storage_failed")
        self.assertEqual((self.output / control.RECEIPT_NAME).read_bytes(), sentinel)
        self.assertEqual((owned_output / control.ARCHIVE_NAME).read_bytes(), BODY)
        self.assertEqual(self.receipt(owned_output / control.RECEIPT_NAME)["outcome"], "pass")

    def test_recovery_open_race_cannot_truncate_last_original(self):
        real_open = os.open
        recovering = False
        owned_receipt = self.output / "owned-receipt.json"
        receipt = self.output / control.RECEIPT_NAME
        archive = self.output / control.ARCHIVE_NAME

        def begin_recovery():
            nonlocal recovering
            recovering = True

        def replace_before_open(path, flags, *args, **kwargs):
            if recovering and path == control.RECEIPT_NAME:
                receipt.rename(owned_receipt)
                os.link(archive, receipt)
            return real_open(path, flags, *args, **kwargs)

        with self.close_failures(directory=True, after_directory=begin_recovery), \
                mock.patch.object(control.os, "open", side_effect=replace_before_open):
            with self.assertRaises(Exception) as caught:
                control.acquire_control(self.output, opener=self.opener)
        self.assert_sanitized_failure(caught.exception, "storage_failed")
        self.assertEqual(archive.read_bytes(), BODY)
        self.assertEqual(receipt.read_bytes(), BODY)
        self.assertTrue(control._same_inode(archive.stat(), receipt.stat()))
        self.assertEqual(self.receipt(owned_receipt)["outcome"], "pass")

    def test_recovery_close_errors_are_bounded_and_both_descriptors_are_released(self):
        real_open = os.open
        recovering = False
        recovery_descriptors, close_attempts = {}, []

        def begin_recovery():
            nonlocal recovering
            recovering = True

        def record_open(path, flags, *args, **kwargs):
            descriptor = real_open(path, flags, *args, **kwargs)
            if recovering and path == control.RECEIPT_NAME:
                recovery_descriptors.update(receipt=descriptor, directory=kwargs["dir_fd"])
            return descriptor

        with self.close_failures(directory=True, after_directory=begin_recovery), \
                mock.patch.object(control.os, "open", side_effect=record_open):
            outer_close = os.close

            def fail_recovery_close(descriptor):
                outer_close(descriptor)
                for name, owned in recovery_descriptors.items():
                    if descriptor == owned:
                        close_attempts.append(name)
                        raise OSError(errno.EIO, "synthetic-private-detail " + AZURE)

            with mock.patch.object(control.os, "close", side_effect=fail_recovery_close):
                with self.assertRaises(Exception) as caught:
                    control.acquire_control(self.output, opener=self.opener)
            self.assertEqual(close_attempts, ["receipt", "directory"])
            self.assert_released(*recovery_descriptors.values())
        self.assert_sanitized_failure(caught.exception, "storage_failed")
        self.assertEqual(self.receipt()["reason_code"], "storage_failed")
        self.assertFalse(self.receipt()["original_verified"])
        self.assertEqual((self.output / control.ARCHIVE_NAME).read_bytes(), BODY)


if __name__ == "__main__":
    unittest.main()
