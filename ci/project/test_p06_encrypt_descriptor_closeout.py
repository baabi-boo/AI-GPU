# SPDX-License-Identifier: Apache-2.0
"""Descriptor setup and committed-publication checks with synthetic age output."""

import errno
import hashlib
import json
import os
import unittest
from unittest import mock

import p06_qualified_warm_encrypt as encrypt
from test_p06_encrypt_operational_failures import encryption_fixture


class EncryptionDescriptorCloseoutTests(unittest.TestCase):
    def _is_open(self, descriptor):
        try:
            os.fstat(descriptor)
            return True
        except OSError as error:
            self.assertEqual(error.errno, errno.EBADF)
            return False

    def _check_fchmod_failure(self, failure, cleanup_failure=None):
        real_open, real_close, real_fchmod = os.open, os.close, os.fchmod
        with encryption_fixture() as fixture:
            source_before = fixture.source_bytes()
            owned = unrelated = None
            identity = None
            injected = False
            closed = []

            def record_open(name, flags, *args, **kwargs):
                nonlocal owned, identity
                descriptor = real_open(name, flags, *args, **kwargs)
                if name == encrypt.INCOMPLETE_NAME:
                    owned = descriptor
                    info = os.fstat(descriptor)
                    identity = (info.st_dev, info.st_ino)
                return descriptor

            def fail_fchmod(descriptor, mode):
                nonlocal injected
                if descriptor == owned and not injected:
                    injected = True
                    raise failure
                return real_fchmod(descriptor, mode)

            def record_close(descriptor):
                nonlocal unrelated
                if descriptor != owned:
                    return real_close(descriptor)
                closed.append(descriptor)
                real_close(descriptor)
                if cleanup_failure is not None:
                    # A close can consume the fd and report failure after its reuse.
                    unrelated = real_open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
                    self.assertEqual(unrelated, descriptor)
                    raise cleanup_failure

            try:
                with mock.patch.object(encrypt.os, "open", side_effect=record_open), \
                        mock.patch.object(encrypt.os, "fchmod", side_effect=fail_fchmod), \
                        mock.patch.object(encrypt.os, "close", side_effect=record_close), \
                        mock.patch.object(encrypt.subprocess, "Popen") as launch:
                    with self.assertRaises(type(failure)) as caught:
                        fixture.run_encrypt()
                self.assertIs(caught.exception, failure)
                launch.assert_not_called()
                self.assertFalse(fixture.audit.exists())
                self.assertFalse(fixture.capture.exists())
                self.assertEqual(fixture.source_bytes(), source_before)
                fixture.assert_failed_public()
                diagnostic = json.loads((fixture.private / encrypt.DIAGNOSTIC_NAME).read_bytes())
                self.assertEqual(diagnostic["error_type"], type(failure).__name__)
                self.assertEqual(diagnostic["stage"], "encryption")
                self.assertFalse(diagnostic["publication_committed"])
                self.assertEqual(closed, [owned])
                if cleanup_failure is None:
                    self.assertFalse(self._is_open(owned))
                else:
                    self.assertIsNotNone(unrelated)
                    self.assertTrue(self._is_open(unrelated))
            finally:
                if unrelated is not None and self._is_open(unrelated):
                    real_close(unrelated)
                elif owned is not None and self._is_open(owned):
                    info = os.fstat(owned)
                    if (info.st_dev, info.st_ino) == identity:
                        real_close(owned)

    def test_fchmod_error_releases_raw_descriptor_before_age_launch(self):
        self._check_fchmod_failure(OSError(errno.EIO, "exclusive chmod failed"))

    def test_fchmod_interrupt_releases_raw_descriptor_before_age_launch(self):
        self._check_fchmod_failure(KeyboardInterrupt("exclusive chmod interrupted"))

    def test_failed_consuming_close_preserves_original_error_and_reused_descriptor(self):
        for failure in (OSError(errno.EIO, "exclusive chmod failed"),
                        KeyboardInterrupt("exclusive chmod interrupted")):
            for cleanup_failure in (OSError(errno.ENOSPC, "exclusive close failed"),
                                    KeyboardInterrupt("exclusive close interrupted")):
                with self.subTest(failure=type(failure).__name__, cleanup=type(cleanup_failure).__name__):
                    self._check_fchmod_failure(failure, cleanup_failure)

    def test_public_file_drift_during_private_cleanup_cannot_return_success(self):
        real_unlink = os.unlink
        for boundary in (encrypt.INCOMPLETE_NAME, encrypt.PRIVATE_SUMMARY_NAME):
            for public_name in (encrypt.CIPHERTEXT_NAME, encrypt.SUMMARY_NAME):
                for mutation in ("replace", "rewrite", "remove"):
                    with self.subTest(boundary=boundary, public=public_name, mutation=mutation), \
                            encryption_fixture() as fixture:
                        source_before = fixture.source_bytes()
                        retained = {}
                        changed = None
                        public = fixture.output / public_name
                        moved = fixture.root / "displaced-public-file"

                        def mutate_after_private_unlink(name, **kwargs):
                            nonlocal changed
                            result = real_unlink(name, **kwargs)
                            if name == boundary:
                                retained.update({path.name: path.read_bytes()
                                                 for path in fixture.output.iterdir()})
                                before = public.stat()
                                if mutation == "rewrite":
                                    body = bytearray(retained[public_name])
                                    body[-1] ^= 1
                                    changed = bytes(body)
                                    public.write_bytes(changed)
                                    os.utime(public, ns=(before.st_atime_ns, before.st_mtime_ns))
                                    self.assertEqual(public.stat().st_ino, before.st_ino)
                                else:
                                    public.rename(moved)
                                    if mutation == "replace":
                                        changed = b"unrelated public owner"
                                        public.write_bytes(changed)
                                        self.assertNotEqual(public.stat().st_ino, before.st_ino)
                            return result

                        with mock.patch.object(encrypt.os, "unlink", side_effect=mutate_after_private_unlink):
                            with self.assertRaisesRegex(encrypt.EncryptionError, "public-output-changed"):
                                fixture.run_encrypt()

                        self.assertEqual(set(retained), {encrypt.CIPHERTEXT_NAME, encrypt.SUMMARY_NAME})
                        for name, body in retained.items():
                            if name != public_name:
                                self.assertEqual((fixture.output / name).read_bytes(), body)
                        if mutation == "remove":
                            self.assertFalse(public.exists())
                        else:
                            self.assertEqual(public.read_bytes(), changed)
                        if mutation != "rewrite":
                            self.assertEqual(moved.read_bytes(), retained[public_name])
                        self.assertFalse((fixture.private / encrypt.INCOMPLETE_NAME).exists())
                        self.assertFalse((fixture.private / encrypt.PRIVATE_SUMMARY_NAME).exists())
                        diagnostic = json.loads((fixture.private / encrypt.DIAGNOSTIC_NAME).read_bytes())
                        self.assertEqual(diagnostic["stage"], "private-cleanup")
                        self.assertTrue(diagnostic["publication_committed"])
                        self.assertFalse(diagnostic["encryption_passed"])
                        self.assertTrue(diagnostic["cleanup_complete"])
                        self.assertEqual(fixture.source_bytes(), source_before)

    def test_unchanged_publication_returns_matching_complete_pair(self):
        with encryption_fixture() as fixture:
            source_before = fixture.source_bytes()
            summary = fixture.run_encrypt()
            ciphertext = (fixture.output / encrypt.CIPHERTEXT_NAME).read_bytes()
            self.assertTrue(summary["encryption_passed"])
            self.assertEqual(summary["ciphertext_bytes"], len(ciphertext))
            self.assertEqual(summary["ciphertext_sha256"], hashlib.sha256(ciphertext).hexdigest())
            self.assertEqual(json.loads((fixture.output / encrypt.SUMMARY_NAME).read_bytes()), summary)
            self.assertEqual({path.name for path in fixture.output.iterdir()},
                             {encrypt.CIPHERTEXT_NAME, encrypt.SUMMARY_NAME})
            self.assertEqual({path.name for path in fixture.private.iterdir()}, {encrypt.STDERR_NAME})
            self.assertEqual(fixture.source_bytes(), source_before)
            fixture.verify_captured_tar(source_before)


if __name__ == "__main__":
    unittest.main()
