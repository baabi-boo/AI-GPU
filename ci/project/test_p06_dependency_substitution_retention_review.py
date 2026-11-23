# SPDX-License-Identifier: Apache-2.0
"""Independent control retention checks with a real archive-reader boundary.

The complete control fixture uses invented dependency/native observations. Only
the tiny-recorder test compiles host libraries; no GPU workload is executed.
"""

from pathlib import Path
import tempfile
import unittest
import zipfile

import p06_dependency_control_replay as replay
from test_p06_dependency_control_replay import SyntheticControls, SyntheticNativeWithControlTools
from test_p06_dependency_native_replay import descriptor, digest
import test_p06_dependency_substitution as tiny_tests


LOCK = "payloads/.retention.lock"


class SubstitutionRetentionReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = SyntheticNativeWithControlTools()
        cls.native = cls.original.reader()
        cls.native.run()

    def setUp(self):
        self.packet = SyntheticControls(self.original, self.native)

    def rebind_lock(self, body):
        files, report = self.packet.substitution_files, self.packet.substitution_report
        if body is None:
            del files[LOCK]
        else:
            files[LOCK] = body
        for key in ("control_products_before", "control_products_after"):
            rows = [row for row in report[key] if row["path"] != LOCK]
            if body is not None:
                rows.append(descriptor(LOCK, body))
            report[key] = sorted(rows, key=lambda row: row["path"])

    def replay_control_zip(self):
        self.packet.finish_substitution()
        with tempfile.TemporaryDirectory(prefix="p06-control-retention-review-") as directory:
            archive_path = Path(directory) / "control.zip"
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, body in sorted(self.packet.substitution_files.items()):
                    archive.writestr(name, body)
            with self.native.api.ArchiveReader(archive_path, digest(archive_path.read_bytes())) as archive:
                return replay.verify_substitution_view(archive.view(""), native=self.native,
                    expected_report_sha256=self.packet.substitution_pin,
                    expected_native_report_sha256=self.packet.native_pin)

    def test_empty_retention_lock_is_part_of_complete_frozen_control(self):
        self.assertEqual(self.packet.substitution_files[LOCK], b"")
        expected = descriptor(LOCK, b"")
        for key in ("control_products_before", "control_products_after"):
            self.assertIn(expected, self.packet.substitution_report[key])
        result = self.replay_control_zip()
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["retained_files_checked"], len(self.packet.substitution_files))
        self.assertEqual(result["control_counts"]["launches"], 33)
        self.assertIs(result["managed_population_included"], False)
        self.assertIs(result["retained_code_executed"], False)

    def test_missing_retention_lock_is_rejected_even_with_rebound_inventories(self):
        self.rebind_lock(None)
        with self.assertRaisesRegex(ValueError, r"retention\.lock"):
            self.replay_control_zip()

    def test_nonempty_retention_lock_is_rejected_even_with_rebound_inventories(self):
        self.rebind_lock(b"unexpected lock contents\n")
        with self.assertRaisesRegex(ValueError, "substitution retention lock"):
            self.replay_control_zip()

    def test_actual_tiny_recorder_leaves_the_empty_retention_lock(self):
        fixture = tiny_tests.ActualSubstitutionBuildTests(
            "test_actual_fresh_marker_library_preserves_tiny_numerics_and_is_byte_different")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.build_control()
        self.assertEqual((fixture.output / LOCK).read_bytes(), b"")
        self.assertEqual(len(list((fixture.output / "records").glob("*.json"))), 2)
        checked = fixture.verify()
        self.assertNotEqual(checked["alternate_product"]["sha256"], checked["original_product"]["sha256"])


if __name__ == "__main__":
    unittest.main()
