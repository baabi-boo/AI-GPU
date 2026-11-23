# SPDX-License-Identifier: Apache-2.0
"""Current-reader trust controls; no retained packet or process is executed."""

import hashlib
from pathlib import Path
import unittest
from unittest import mock

import p06_dependency_build as builder
import p06_dependency_control_replay as controls


class ControlReaderTrustReviewTests(unittest.TestCase):
    def check_unopened_original(self):
        return controls.replay_archive(
            Path("/must-not-open-current-helper-review.zip"), "0" * 64,
            expected_revision="a" * 40,
            expected_receipt_sha256="1" * 64,
            expected_native_report_sha256="2" * 64,
            expected_source_manifest_sha256="3" * 64,
            expected_probe_report_sha256="4" * 64,
            expected_substitution_report_sha256="5" * 64,
        )

    def test_transitively_imported_builder_wrong_origin_rejects_before_archive_api(self):
        wrong_origin = str(controls.ROOT / "ci/project/p06_pending_probe.py")
        with mock.patch.object(builder, "__file__", wrong_origin), \
                mock.patch.object(controls.native_replay.dependency_replay, "_archive_api",
                    side_effect=AssertionError("archive reached before helper origin check")) as archive, \
                self.assertRaisesRegex(ValueError, "helper loaded outside the trusted checkout"):
            self.check_unopened_original()
        archive.assert_not_called()

    def test_actual_builder_hash_is_frozen_and_changed_bytes_reject_before_archive_api(self):
        relative = "ci/project/p06_dependency_build.py"
        source = controls.ROOT / relative
        body = source.read_bytes()
        rows = [row for row in controls.TRUSTED_READER_SOURCES if row["path"] == relative]
        self.assertEqual(rows, [{"path": relative,
            "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}])
        original_read = Path.read_bytes

        def changed_current_bytes(path):
            return body + b"\n# simulated current-helper drift\n" if path == source else original_read(path)

        with mock.patch.object(Path, "read_bytes", new=changed_current_bytes), \
                mock.patch.object(controls.native_replay.dependency_replay, "_archive_api",
                    side_effect=AssertionError("archive reached before helper drift check")) as archive, \
                self.assertRaisesRegex(ValueError, "trusted control replay source changed after import"):
            self.check_unopened_original()
        archive.assert_not_called()


if __name__ == "__main__":
    unittest.main()
