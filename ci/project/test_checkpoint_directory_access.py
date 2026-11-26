# SPDX-License-Identifier: Apache-2.0
"""Checkpoint publication needs directory write/search access, not read access."""

from contextlib import contextmanager
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest

import p02_matrix as matrix
import p04_ci_prepare as preparation


@contextmanager
def write_search_only(directory):
    previous_mode = stat.S_IMODE(directory.stat().st_mode)
    directory.chmod(0o300)
    try:
        yield
    finally:
        directory.chmod(previous_mode)


class CheckpointDirectoryAccessTests(unittest.TestCase):
    def test_create_and_replace_without_directory_read_permission(self):
        with tempfile.TemporaryDirectory(prefix="checkpoint-access-") as directory:
            parent = Path(directory)
            path = parent / "report.json"
            with write_search_only(parent):
                for state in ("first", "final"):
                    with self.subTest(state=state):
                        value = {"state": state}
                        matrix._write_json(path, value)
                        self.assertEqual(json.loads(path.read_bytes()), value)
                        self.assertFalse(path.with_name(path.name + ".tmp").exists())
                        self.assertEqual(stat.S_IMODE(parent.stat().st_mode), 0o300)
            self.assertEqual(list(parent.iterdir()), [path])

    def test_preparation_writes_blocked_receipt_without_directory_read_permission(self):
        with tempfile.TemporaryDirectory(prefix="checkpoint-prepare-access-") as directory:
            workspace = Path(directory)
            evidence = workspace / "evidence"
            evidence.mkdir()
            args = SimpleNamespace(
                source_dir=preparation.ROOT, workspace_dir=workspace,
                expected_revision="invalid", backend="simx", format="both",
                toolchain_id="not-restored", toolchain_cache_key="not-restored",
                third_party_cache_key="not-restored", expected_third_party_key="not-restored",
            )
            with write_search_only(evidence):
                report = preparation.prepare(args)
                self.assertEqual(report["outcome"], "blocked")
                self.assertEqual(report["reason"], "invalid source revision")
                self.assertEqual(report["native_execution"], "not_run")
                self.assertIs(report["tools_relocated"], False)
                self.assertEqual(json.loads((evidence / "preparation.json").read_bytes()), report)
                self.assertEqual(stat.S_IMODE(evidence.stat().st_mode), 0o300)
            self.assertEqual(list(evidence.iterdir()), [evidence / "preparation.json"])


if __name__ == "__main__":
    unittest.main()
