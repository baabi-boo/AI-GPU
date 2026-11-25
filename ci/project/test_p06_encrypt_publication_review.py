# SPDX-License-Identifier: Apache-2.0
"""Independent last-copy checks at the encryption publication boundary."""

import hashlib
import json
import os
import unittest
from unittest import mock

import p06_qualified_warm_encrypt as encrypt
from test_p06_encrypt_operational_failures import encryption_fixture


class EncryptionPublicationReviewTests(unittest.TestCase):
    def test_path_drift_after_first_public_link_preserves_last_ciphertext(self):
        original_link = os.link
        for replacement in (False, True):
            with self.subTest(replacement=replacement), encryption_fixture() as fixture:
                moved = fixture.output.with_name("displaced-output")
                retained = []
                source_before = fixture.source_bytes()

                def displace_after_ciphertext_link(source, target, **kwargs):
                    result = original_link(source, target, **kwargs)
                    if target == encrypt.CIPHERTEXT_NAME:
                        retained.append((fixture.output / target).read_bytes())
                        (fixture.private / encrypt.INCOMPLETE_NAME).unlink()
                        fixture.output.rename(moved)
                        if replacement:
                            fixture.output.mkdir()
                            (fixture.output / "unrelated").write_bytes(b"unrelated owner")
                    return result

                with mock.patch.object(encrypt.os, "link", side_effect=displace_after_ciphertext_link):
                    with self.assertRaisesRegex(encrypt.EncryptionError, "public-output-changed"):
                        fixture.run_encrypt()

                self.assertEqual(len(retained), 1)
                ciphertext = (moved / encrypt.CIPHERTEXT_NAME).read_bytes()
                self.assertEqual(ciphertext, retained[0])
                self.assertFalse((fixture.private / encrypt.INCOMPLETE_NAME).exists())
                private_summary = json.loads((fixture.private / encrypt.PRIVATE_SUMMARY_NAME).read_bytes())
                self.assertEqual(private_summary["ciphertext_sha256"], hashlib.sha256(ciphertext).hexdigest())
                self.assertEqual(private_summary["ciphertext_bytes"], len(ciphertext))
                public_summary = json.loads((moved / encrypt.SUMMARY_NAME).read_bytes())
                self.assertFalse(public_summary["encryption_passed"])
                diagnostic = json.loads((fixture.private / encrypt.DIAGNOSTIC_NAME).read_bytes())
                self.assertFalse(diagnostic["publication_committed"])
                self.assertTrue(diagnostic["cleanup_complete"])
                self.assertEqual(fixture.source_bytes(), source_before)
                if replacement:
                    self.assertEqual(list(fixture.output.iterdir()), [fixture.output / "unrelated"])
                    self.assertEqual((fixture.output / "unrelated").read_bytes(), b"unrelated owner")
                else:
                    self.assertFalse(fixture.output.exists())


if __name__ == "__main__":
    unittest.main()
