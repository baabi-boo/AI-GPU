# SPDX-License-Identifier: Apache-2.0
"""Focused staging failure controls using actual temporary files."""

from pathlib import Path
import tempfile
import unittest
from unittest import mock

import p06_dependency_build as build


class StagingFailureReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-staging-review-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "selected-input"
        self.body = b"complete selected dependency input\n"
        self.source.write_bytes(self.body)
        self.source.chmod(0o755)
        baseline = self.root / "baseline/input"
        observed = build.stage_file(self.source, baseline)
        self.assertEqual(observed, build.identity(baseline))
        self.assertEqual(baseline.read_bytes(), self.body)
        self.assertEqual(baseline.stat().st_mode & 0o777, 0o755)

    def test_partial_copy_failure_is_preserved_and_cannot_be_reused(self):
        destination = self.root / "partial/input"

        def interrupted(source, target, **kwargs):
            target.write(source.read(7))
            raise OSError("staging stream interrupted")

        with mock.patch.object(build.shutil, "copyfileobj", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "staging stream interrupted"):
                build.stage_file(self.source, destination)
        self.assertEqual(destination.read_bytes(), self.body[:7])
        self.assertEqual(self.source.read_bytes(), self.body)
        with self.assertRaisesRegex(ValueError, "destination is not fresh"):
            build.stage_file(self.source, destination)
        self.assertEqual(destination.read_bytes(), self.body[:7])

    def test_source_change_during_copy_cannot_become_a_staged_identity(self):
        destination = self.root / "changed/input"
        copy_file = build.shutil.copyfileobj
        updated = b"updated dependency input\n"

        def changed(source, target, **kwargs):
            copy_file(source, target, **kwargs)
            self.source.write_bytes(updated)

        with mock.patch.object(build.shutil, "copyfileobj", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "input changed during staging"):
                build.stage_file(self.source, destination)
        self.assertEqual(destination.read_bytes(), self.body)
        self.assertEqual(self.source.read_bytes(), updated)
        with self.assertRaisesRegex(ValueError, "destination is not fresh"):
            build.stage_file(self.source, destination)
        self.assertEqual(destination.read_bytes(), self.body)


if __name__ == "__main__":
    unittest.main()
