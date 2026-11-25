# SPDX-License-Identifier: Apache-2.0
"""Filesystem fault checks using the existing synthetic age subprocess fixture."""

from contextlib import contextmanager
import hashlib
import json
import os
import stat
import unittest
from unittest import mock

import p06_qualified_warm_encrypt as encrypt
import test_p06_qualified_warm_encrypt as fixtures


@contextmanager
def encryption_fixture():
    fixture = fixtures.EncryptedRetentionTests()
    try:
        fixture.setUp()
        parent = fixture.root / "destination"
        parent.mkdir()
        fixture.output = parent / "public-output"
        fixture.private = parent / "public-output.PRIVATE"
        yield fixture
    finally:
        fixture.doCleanups()


class EncryptionOperationalFailuresTests(unittest.TestCase):
    def _replace(self, path, replacement):
        moved = path.with_name(path.name + "-moved")
        path.rename(moved)
        if replacement == "directory":
            path.mkdir()
            (path / "unrelated").write_bytes(b"unrelated owner")
        elif replacement == "symlink":
            path.symlink_to(moved, target_is_directory=True)
        return moved

    def _assert_retained_failure(self, output, private):
        self.assertFalse((output / encrypt.CIPHERTEXT_NAME).exists())
        summary = json.loads((output / encrypt.SUMMARY_NAME).read_bytes())
        self.assertFalse(summary["encryption_passed"])
        self.assertGreater((private / encrypt.INCOMPLETE_NAME).stat().st_size, 0)
        diagnostic = json.loads((private / encrypt.DIAGNOSTIC_NAME).read_bytes())
        self.assertFalse(diagnostic["publication_committed"])

    def test_changed_named_paths_after_final_inventory_reject_publication(self):
        original = encrypt._inventory
        for target in ("source", "output", "private", "parent"):
            for replacement in ("absent", "directory", "symlink"):
                with self.subTest(target=target, replacement=replacement), encryption_fixture() as fixture:
                    calls = 0
                    moved = None
                    path = fixture.output.parent if target == "parent" else getattr(fixture, target)

                    def replace_after_inventory(root, deadline):
                        nonlocal calls, moved
                        result = original(root, deadline)
                        calls += 1
                        if calls == 2:
                            moved = self._replace(path, replacement)
                        return result

                    with mock.patch.object(encrypt, "_inventory", side_effect=replace_after_inventory):
                        with self.assertRaises((OSError, encrypt.EncryptionError)):
                            fixture.run_encrypt()
                    output = moved if target == "output" else fixture.output
                    private = moved if target == "private" else fixture.private
                    if target == "parent":
                        output, private = moved / output.name, moved / private.name
                    self._assert_retained_failure(output, private)
                    if replacement == "directory":
                        self.assertEqual(list(path.iterdir()), [path / "unrelated"])
                        self.assertEqual((path / "unrelated").read_bytes(), b"unrelated owner")

    def test_changed_named_paths_during_publication_roll_back_owned_links(self):
        original = encrypt.os.fsync
        for target in ("source", "output", "private", "parent"):
            with self.subTest(target=target), encryption_fixture() as fixture:
                moved = None
                path = fixture.output.parent if target == "parent" else getattr(fixture, target)

                def replace_after_sync(fd):
                    nonlocal moved
                    result = original(fd)
                    if stat.S_ISDIR(os.fstat(fd).st_mode) and moved is None:
                        moved = self._replace(path, "directory")
                    return result

                with mock.patch.object(encrypt.os, "fsync", side_effect=replace_after_sync):
                    with self.assertRaises((OSError, encrypt.EncryptionError)):
                        fixture.run_encrypt()
                output = moved if target == "output" else fixture.output
                private = moved if target == "private" else fixture.private
                if target == "parent":
                    output, private = moved / output.name, moved / private.name
                self._assert_retained_failure(output, private)
                self.assertEqual(list(path.iterdir()), [path / "unrelated"])

    def test_source_replacement_before_first_inventory_is_not_rebound(self):
        original = encrypt._inventory
        with encryption_fixture() as fixture:
            replaced = False

            def replace_before_inventory(root, deadline):
                nonlocal replaced
                if not replaced:
                    replaced = True
                    self._replace(fixture.source, "directory")
                return original(root, deadline)

            with mock.patch.object(encrypt, "_inventory", side_effect=replace_before_inventory):
                with self.assertRaises((OSError, encrypt.EncryptionError)):
                    fixture.run_encrypt()
            self.assertFalse(fixture.audit.exists())
            self.assertFalse((fixture.output / encrypt.CIPHERTEXT_NAME).exists())

    def test_replaced_ancestor_with_original_leaf_directories_is_rejected(self):
        original = encrypt._inventory
        with encryption_fixture() as fixture:
            calls = 0

            def replace_parent_after_inventory(root, deadline):
                nonlocal calls
                result = original(root, deadline)
                calls += 1
                if calls == 2:
                    identities = [path.stat().st_ino for path in (fixture.output, fixture.private)]
                    moved = self._replace(fixture.output.parent, "directory")
                    for path in (fixture.output, fixture.private):
                        (moved / path.name).rename(path)
                    self.assertEqual([path.stat().st_ino for path in (fixture.output, fixture.private)],
                                     identities)
                return result

            with mock.patch.object(encrypt, "_inventory", side_effect=replace_parent_after_inventory):
                with self.assertRaisesRegex(encrypt.EncryptionError, "public-output-changed"):
                    fixture.run_encrypt()
            self._assert_retained_failure(fixture.output, fixture.private)
            self.assertEqual((fixture.output.parent / "unrelated").read_bytes(), b"unrelated owner")

    def test_path_change_during_committed_cleanup_reports_failure_and_preserves_ciphertext(self):
        original = encrypt.os.unlink
        for target in ("output", "parent"):
            with self.subTest(target=target), encryption_fixture() as fixture:
                moved = None
                path = fixture.output.parent if target == "parent" else fixture.output

                def replace_after_private_cleanup(name, **kwargs):
                    nonlocal moved
                    result = original(name, **kwargs)
                    if name == encrypt.PRIVATE_SUMMARY_NAME:
                        moved = self._replace(path, "directory")
                    return result

                with mock.patch.object(encrypt.os, "unlink", side_effect=replace_after_private_cleanup):
                    with self.assertRaisesRegex(encrypt.EncryptionError, "public-output-changed"):
                        fixture.run_encrypt()
                output = moved / fixture.output.name if target == "parent" else moved
                private = moved / fixture.private.name if target == "parent" else fixture.private
                ciphertext = (output / encrypt.CIPHERTEXT_NAME).read_bytes()
                summary = json.loads((output / encrypt.SUMMARY_NAME).read_bytes())
                self.assertTrue(summary["encryption_passed"])
                self.assertEqual(summary["ciphertext_sha256"], hashlib.sha256(ciphertext).hexdigest())
                self.assertFalse((private / encrypt.INCOMPLETE_NAME).exists())
                diagnostic = json.loads((private / encrypt.DIAGNOSTIC_NAME).read_bytes())
                self.assertTrue(diagnostic["publication_committed"])
                self.assertEqual(list(path.iterdir()), [path / "unrelated"])

    def test_interrupt_after_committed_private_unlink_keeps_last_ciphertext(self):
        original = encrypt.os.unlink
        with encryption_fixture() as fixture:
            retained = []

            def interrupt_private_summary(name, **kwargs):
                if name == encrypt.PRIVATE_SUMMARY_NAME:
                    self.assertFalse((fixture.private / encrypt.INCOMPLETE_NAME).exists())
                    retained.append((fixture.output / encrypt.CIPHERTEXT_NAME).read_bytes())
                    original(name, **kwargs)
                    raise KeyboardInterrupt("after-private-summary-cleanup")
                return original(name, **kwargs)

            with mock.patch.object(encrypt.os, "unlink", side_effect=interrupt_private_summary):
                with self.assertRaisesRegex(KeyboardInterrupt, "after-private-summary-cleanup"):
                    fixture.run_encrypt()
            self.assertEqual(len(retained), 1)
            ciphertext = (fixture.output / encrypt.CIPHERTEXT_NAME).read_bytes()
            self.assertEqual(ciphertext, retained[0])
            summary = json.loads((fixture.output / encrypt.SUMMARY_NAME).read_bytes())
            self.assertTrue(summary["encryption_passed"])
            self.assertEqual(summary["ciphertext_sha256"], hashlib.sha256(ciphertext).hexdigest())
            diagnostic = json.loads((fixture.private / encrypt.DIAGNOSTIC_NAME).read_bytes())
            self.assertTrue(diagnostic["publication_committed"])


if __name__ == "__main__":
    unittest.main()
