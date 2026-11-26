# SPDX-License-Identifier: Apache-2.0
"""Named-directory drift during the final synthetic ciphertext and summary reads."""

import hashlib
import json
import os
import unittest
from unittest import mock

import p06_qualified_warm_encrypt as encrypt
from test_p06_encrypt_operational_failures import encryption_fixture


class EncryptionFinalDirectoryTests(unittest.TestCase):
    def test_output_directory_drift_during_final_reads_preserves_committed_pair(self):
        real_verify, real_read = encrypt._verify_public_file, os.read
        for public_name in (encrypt.CIPHERTEXT_NAME, encrypt.SUMMARY_NAME):
            for replacement in (False, True):
                with self.subTest(public=public_name, replacement=replacement), \
                        encryption_fixture() as fixture:
                    source_before = fixture.source_bytes()
                    moved = fixture.output.with_name("displaced-output")
                    retained = {}
                    verified = []

                    def verify_with_directory_drift(directory_fd, name, identity, count, digest, deadline):
                        def displace_after_read(fd, size):
                            body = real_read(fd, size)
                            if body and not retained:
                                info = os.fstat(fd)
                                self.assertEqual((info.st_dev, info.st_ino), identity)
                                retained.update({path.name: path.read_bytes()
                                                 for path in fixture.output.iterdir()})
                                fixture.output.rename(moved)
                                if replacement:
                                    fixture.output.mkdir()
                                    (fixture.output / "unrelated").write_bytes(b"unrelated owner")
                            return body

                        if name == public_name:
                            with mock.patch.object(encrypt.os, "read", side_effect=displace_after_read):
                                real_verify(directory_fd, name, identity, count, digest, deadline)
                        else:
                            real_verify(directory_fd, name, identity, count, digest, deadline)
                        verified.append(name)

                    with mock.patch.object(encrypt, "_verify_public_file", side_effect=verify_with_directory_drift):
                        with self.assertRaisesRegex(encrypt.EncryptionError, "public-output-changed"):
                            fixture.run_encrypt()

                    self.assertEqual(verified, [encrypt.CIPHERTEXT_NAME, encrypt.SUMMARY_NAME])
                    self.assertEqual(set(retained), {encrypt.CIPHERTEXT_NAME, encrypt.SUMMARY_NAME})
                    self.assertEqual({path.name: path.read_bytes() for path in moved.iterdir()}, retained)
                    summary = json.loads(retained[encrypt.SUMMARY_NAME])
                    ciphertext = retained[encrypt.CIPHERTEXT_NAME]
                    self.assertTrue(summary["encryption_passed"])
                    self.assertEqual(summary["ciphertext_sha256"], hashlib.sha256(ciphertext).hexdigest())
                    self.assertEqual(summary["ciphertext_bytes"], len(ciphertext))
                    self.assertFalse((fixture.private / encrypt.INCOMPLETE_NAME).exists())
                    self.assertFalse((fixture.private / encrypt.PRIVATE_SUMMARY_NAME).exists())
                    diagnostic = json.loads((fixture.private / encrypt.DIAGNOSTIC_NAME).read_bytes())
                    self.assertEqual(diagnostic["stage"], "private-cleanup")
                    self.assertEqual(diagnostic["error_type"], "EncryptionError")
                    self.assertTrue(diagnostic["publication_committed"])
                    self.assertFalse(diagnostic["encryption_passed"])
                    self.assertTrue(diagnostic["cleanup_complete"])
                    self.assertEqual(fixture.source_bytes(), source_before)
                    if replacement:
                        self.assertEqual({path.name: path.read_bytes() for path in fixture.output.iterdir()},
                                         {"unrelated": b"unrelated owner"})
                    else:
                        self.assertFalse(fixture.output.exists())


if __name__ == "__main__":
    unittest.main()
