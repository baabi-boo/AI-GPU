# SPDX-License-Identifier: Apache-2.0
"""Real filesystem race and identity controls; historical replay is synthetic."""

import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import p06_counter_qualification_admission as admission
import p06_dependency_admission as dependency
from test_p06_counter_qualification_admission import AdmissionInputs


class QualificationAdmissionIdentityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="qualification-admission-adversarial-")
        self.addCleanup(directory.cleanup)
        self.inputs = AdmissionInputs(directory.name)
        patches = self.inputs.patches()
        self.addCleanup(patches.close)

    def test_dependency_subclass_cannot_bypass_complete_admission_gate(self):
        class AlternateAdmission(dependency.Admission):
            pass

        alternate = object.__new__(AlternateAdmission)
        with self.assertRaisesRegex(ValueError, "complete live dependency admission"):
            self.inputs.admit(dependency_admission=alternate)
        self.inputs.diagnostic_replay.assert_not_called()
        self.inputs.control_replay.assert_not_called()

    def test_both_dependency_success_flags_require_actual_true(self):
        for name in ("document", "verification"):
            record = getattr(self.inputs.dependency, name)
            for invalid in (False, 1, "true"):
                with self.subTest(record=name, value=invalid):
                    record["fresh_dependency_build_passed"] = invalid
                    with self.assertRaisesRegex(ValueError, "different source or failed build"):
                        self.inputs.admit()
                    record["fresh_dependency_build_passed"] = True
        self.inputs.diagnostic_replay.assert_not_called()
        self.inputs.control_replay.assert_not_called()

    def test_swapping_prerequisite_paths_rejects_before_either_replay(self):
        with self.assertRaisesRegex(ValueError, "selected original"):
            self.inputs.admit(
                diagnostic_archive=self.inputs.archives["controls"],
                control_archive=self.inputs.archives["diagnostics"])
        self.inputs.diagnostic_replay.assert_not_called()
        self.inputs.control_replay.assert_not_called()

    def test_late_archive_alias_invalidates_unchanged_original_bytes(self):
        for name, kind in (("diagnostics", "hardlink"), ("controls", "symlink")):
            with self.subTest(archive=name, alias=kind):
                value = self.inputs.admit()
                path = self.inputs.archives[name]
                retained = path.with_suffix(".retained")
                if kind == "hardlink":
                    retained.hardlink_to(path)
                    expected = "unlinked regular"
                else:
                    path.rename(retained)
                    path.symlink_to(retained)
                    expected = "without symlinks"
                try:
                    with self.assertRaisesRegex(ValueError, expected):
                        value.verify_stable()
                finally:
                    if kind == "hardlink":
                        retained.unlink()
                    else:
                        path.unlink()
                        retained.rename(path)

    def test_late_measurement_parent_symlink_invalidates_same_bytes(self):
        value = self.inputs.admit()
        original = self.inputs.source / "sim/simx"
        moved = self.inputs.root / "same-simx-bytes"
        original.rename(moved)
        original.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "without symlinks"):
            value.verify_stable()


class QualificationInputReadStabilityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="qualification-read-race-")
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "input"
        self.body = b"unchanged authenticated bytes"
        self.path.write_bytes(self.body)

    def replace_with_same_bytes(self):
        replacement = self.path.with_suffix(".replacement")
        replacement.write_bytes(self.body)
        os.replace(replacement, self.path)

    def test_same_byte_replacement_before_open_is_rejected(self):
        real_open = os.open

        def open_after_replacement(path, flags):
            self.assertEqual(Path(path), self.path)
            self.replace_with_same_bytes()
            return real_open(path, flags)

        with mock.patch.object(admission.os, "open", side_effect=open_after_replacement):
            with self.assertRaisesRegex(ValueError, "changed before reading"):
                admission._identity(self.path)

    def test_same_byte_replacement_during_read_is_rejected(self):
        real_fdopen = os.fdopen
        replace = self.replace_with_same_bytes

        class ReplaceAfterFirstRead:
            def __init__(self, descriptor, mode):
                self.stream = real_fdopen(descriptor, mode)
                self.first = True

            def __enter__(self):
                self.stream.__enter__()
                return self

            def __exit__(self, *args):
                return self.stream.__exit__(*args)

            def fileno(self):
                return self.stream.fileno()

            def read(self, count):
                body = self.stream.read(count)
                if self.first:
                    self.first = False
                    replace()
                return body

        with mock.patch.object(admission.os, "fdopen", side_effect=ReplaceAfterFirstRead):
            with self.assertRaisesRegex(ValueError, "changed while reading"):
                admission._identity(self.path)

    def test_content_identity_survives_completed_same_byte_replacement(self):
        before = admission._identity(self.path)
        previous_inode = self.path.stat().st_ino
        self.replace_with_same_bytes()
        self.assertNotEqual(previous_inode, self.path.stat().st_ino)
        self.assertEqual(admission._identity(self.path), before)
        self.assertEqual(before, {"path": str(self.path),
            "sha256": hashlib.sha256(self.body).hexdigest(), "size_bytes": len(self.body)})


if __name__ == "__main__":
    unittest.main()
