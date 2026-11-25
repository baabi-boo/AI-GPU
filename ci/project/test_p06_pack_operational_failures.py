# SPDX-License-Identifier: Apache-2.0
"""Output-directory replacement controls for PRIVATE packaging recovery."""

import json
import os
import unittest
from unittest import mock

import p06_qualified_warm_pack as pack
import test_p06_qualified_warm_pack as fixtures


class PackagingDirectoryIdentityTests(unittest.TestCase):
    setUp = fixtures.PrivatePackagingTests.setUp
    put = fixtures.PrivatePackagingTests.put
    write_json = fixtures.PrivatePackagingTests.write_json
    descriptor = fixtures.PrivatePackagingTests.descriptor
    make_success = fixtures.PrivatePackagingTests.make_success
    arguments = fixtures.PrivatePackagingTests.arguments
    tree_bytes = fixtures.PrivatePackagingTests.tree_bytes

    def replace_output(self, *, symlink=False, collisions=True):
        retained = self.root / "retained-output"
        self.output.rename(retained)
        replacement = self.root / "replacement-output" if symlink else self.output
        replacement.mkdir(mode=0o755)
        if symlink:
            self.output.symlink_to(replacement, target_is_directory=True)
        # Existing unrelated output must survive recovery, including a name
        # that would otherwise be used for a failure receipt.
        names = (pack.ORIGINAL_NAME, pack.RECEIPT_NAME, pack.FAILURE_NAME) if collisions else ("unrelated.log",)
        for name in names:
            (replacement / name).write_bytes(b"unrelated replacement bytes\n")
        self.replacement = replacement
        self.replacement_before = {path.name: path.read_bytes() for path in replacement.iterdir()}
        return retained

    def assert_replacement_preserved(self):
        self.assertEqual({path.name: path.read_bytes() for path in self.replacement.iterdir()},
                         self.replacement_before)

    def retained_failure(self, retained):
        result = json.loads((retained / pack.FAILURE_NAME).read_bytes())
        self.assertFalse(result["packaging_passed"])
        self.assertFalse(result["complete_replay_original_created"])
        self.assertFalse(result["published_receipt_withdrawal_unresolved"])
        self.assertFalse((retained / pack.RECEIPT_NAME).exists())
        return result

    def test_replacement_before_copy_rejects_complete_and_partial_packaging(self):
        original = pack._inventory
        originals = self.tree_bytes()
        for partial in (False, True):
            with self.subTest(partial=partial):
                self.output = self.root / ("output-" + str(partial))
                retained = None

                def replace(selections):
                    nonlocal retained
                    if retained is None:
                        retained = self.replace_output(collisions=False)
                    return original(selections)

                action = pack.package_partial if partial else pack.package_success
                with mock.patch.object(pack, "_inventory", side_effect=replace):
                    with self.assertRaisesRegex(ValueError, "output directory changed"):
                        action(**self.arguments())
                self.assertEqual(self.retained_failure(retained)["stage"], "inventory")
                self.assertEqual(self.tree_bytes(), originals)
                self.assert_replacement_preserved()
                retained.rename(self.root / ("completed-retained-" + str(partial)))

    def test_replacement_after_copy_preserves_owned_incomplete_archive(self):
        original = pack._write_zip
        retained = None

        def replace(path, members):
            nonlocal retained
            original(path, members)
            retained = self.replace_output()

        with mock.patch.object(pack, "_write_zip", side_effect=replace):
            with self.assertRaisesRegex(ValueError, "output directory changed"):
                pack.package_partial(**self.arguments())
        failure = self.retained_failure(retained)
        self.assertEqual([row["filename"] for row in failure["created_files"]],
                         ["incomplete-" + pack.PARTIAL_NAME])
        self.assertGreater((retained / failure["created_files"][0]["filename"]).stat().st_size, 0)
        self.assert_replacement_preserved()

    def test_replacement_after_receipt_publication_withdraws_owned_final_names(self):
        original = pack._publish
        originals = self.tree_bytes()
        for symlink in (False, True):
            with self.subTest(symlink=symlink):
                self.output = self.root / ("output-" + str(symlink))
                retained = None

                def replace(source, target):
                    nonlocal retained
                    original(source, target)
                    if target.name == pack.RECEIPT_NAME:
                        retained = self.replace_output(symlink=symlink)

                with mock.patch.object(pack, "_publish", side_effect=replace):
                    with self.assertRaises((OSError, ValueError)):
                        pack.package_success(**self.arguments())
                failure = self.retained_failure(retained)
                self.assertEqual(failure["stage"], "publish")
                self.assertEqual({row["filename"] for row in failure["created_files"]},
                                 {"incomplete-" + pack.ORIGINAL_NAME, "incomplete-" + pack.ENVELOPE_NAME})
                for name in (pack.ORIGINAL_NAME, pack.ENVELOPE_NAME, pack.RECEIPT_NAME):
                    self.assertFalse((retained / name).exists())
                    self.assertEqual((retained / ("incomplete-" + name)).stat().st_nlink, 1)
                self.assertEqual(self.tree_bytes(), originals)
                self.assert_replacement_preserved()
                retained.rename(self.root / ("completed-retained-" + str(symlink)))

    def test_output_permission_change_is_observed_before_copy(self):
        original = pack._inventory

        def change_permissions(selections):
            os.chmod(self.output, 0o755)
            return original(selections)

        with mock.patch.object(pack, "_inventory", side_effect=change_permissions):
            with self.assertRaisesRegex(ValueError, "output directory changed"):
                pack.package_partial(**self.arguments())
        self.assertEqual(self.retained_failure(self.output)["stage"], "inventory")
        self.assertFalse(list(self.output.glob("*.zip")))


if __name__ == "__main__":
    unittest.main()
