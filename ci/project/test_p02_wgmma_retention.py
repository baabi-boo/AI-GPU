# SPDX-License-Identifier: Apache-2.0
"""Resource controls for matrix artifact retention without processor execution."""

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

import p02_wgmma_matrix as matrix
import test_p02_wgmma_matrix as support


class RetentionTests(unittest.TestCase):
    def scenario(self, **kwargs):
        harness = support.WorkflowTests()
        self.addCleanup(harness.doCleanups)
        return harness.scenario(**kwargs)

    def test_retention_rejects_before_consuming_reserved_space(self):
        report, calls, paths = self.scenario(copy_disk_usage=lambda _: SimpleNamespace(
            free=matrix.BUDGET["min_free_bytes"]))
        self.assertEqual(report["outcome"], "blocked")
        self.assertIn("retained artifact would breach", report["reason"])
        self.assertEqual(calls["budgets"], [])
        self.assertFalse(any(path.is_file() for path in (paths["output"] / "artifacts").rglob("*")))

    def test_reserve_is_rechecked_before_each_file(self):
        first = support.ROOT / ".gitmodules"
        reserve = matrix.BUDGET["min_free_bytes"]
        disk = mock.Mock(side_effect=[SimpleNamespace(free=reserve + first.stat().st_size),
                                      SimpleNamespace(free=reserve)])
        report, calls, paths = self.scenario(copy_disk_usage=disk)
        self.assertEqual(report["outcome"], "blocked")
        self.assertIn("retained artifact would breach", report["reason"])
        self.assertEqual(disk.call_count, 2)
        self.assertEqual(calls["budgets"], [])
        retained = [path for path in (paths["output"] / "artifacts").rglob("*") if path.is_file()]
        self.assertEqual(retained, [paths["output"] / "artifacts/source/.gitmodules"])
        self.assertEqual(retained[0].read_text(), first.read_text())

    def test_successful_retention_uses_bounded_streams_and_preserves_hashes(self):
        original_copy = matrix.shutil.copyfileobj
        original_read_bytes = Path.read_bytes
        copies = []

        def read_bytes(path):
            self.assertNotEqual(path, support.ROOT / ".gitmodules", "retention read an entire source file")
            return original_read_bytes(path)

        def copy(source, destination, length):
            self.assertEqual(length, matrix.MIB)
            copies.append((source.name, destination.name))
            owner = self

            class BoundedReader:
                def read(self, size):
                    owner.assertGreater(size, 0)
                    owner.assertLessEqual(size, matrix.MIB)
                    return source.read(size)

            original_copy(BoundedReader(), destination, length=length)

        with mock.patch.object(Path, "read_bytes", read_bytes), mock.patch.object(
                matrix.shutil, "copyfileobj", side_effect=copy):
            report, _, paths = self.scenario()
        self.assertEqual(report["outcome"], "pass", report["reason"])
        self.assertTrue(copies)
        self.assertEqual(len(copies), len(report["source_snapshots"]))
        self.assertEqual(matrix.hash_artifacts(paths["output"], [row["path"] for row in report["source_snapshots"]]),
                         report["source_snapshots"])

    def test_copy_errors_preserve_a_finished_failure_record(self):
        with mock.patch.object(matrix.shutil, "copyfileobj", side_effect=OSError("retention write failed")):
            report, calls, _ = self.scenario()
        self.assertEqual(report["outcome"], "blocked")
        self.assertEqual(report["reason"], "retention write failed")
        self.assertEqual(report["state"], "finished")
        self.assertEqual(calls["budgets"], [])
        self.assertFalse(report["acceptance_claimed"])


if __name__ == "__main__":
    unittest.main()
