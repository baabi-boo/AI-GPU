# SPDX-License-Identifier: Apache-2.0
"""Reconcile installed and retained file inventories without changing old owners."""

import hashlib
from pathlib import Path
import tempfile
import unittest

import p05_torch_execute as runner


class RetainedInstallationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p05-retained-installation-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.expected = []
        for name, body in (
            ("vortex_ai/__init__.py", b"PACKAGE SOURCE\n"),
            ("vortex_ai/torch_ops.py", b"ADAPTER SOURCE\n"),
            ("vortex_ai-0.1.0.dist-info/METADATA", b"PACKAGE METADATA\n"),
        ):
            path = self.root / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(body)
            self.expected.append({"path": name, "size_bytes": len(body),
                                  "sha256": hashlib.sha256(body).hexdigest()})
        self.expected.sort(key=lambda row: row["path"])

    def test_same_bytes_reconcile_component_and_string_order(self):
        observed = runner.python_run._tree_records(self.root)
        self.assertNotEqual(observed, self.expected)
        with self.assertRaisesRegex(ValueError, "original comparator"):
            runner._same(observed, self.expected, "original comparator")
        runner._verify_retained_installation(self.root, self.expected)

    def test_changed_file_is_still_rejected(self):
        (self.root / "vortex_ai/torch_ops.py").write_bytes(b"CHANGED ADAPTER\n")
        with self.assertRaisesRegex(ValueError, "retained installed binding differs"):
            runner._verify_retained_installation(self.root, self.expected)

    def test_missing_file_is_still_rejected(self):
        (self.root / "vortex_ai/torch_ops.py").unlink()
        with self.assertRaisesRegex(ValueError, "retained installed binding differs"):
            runner._verify_retained_installation(self.root, self.expected)

    def test_extra_file_is_still_rejected(self):
        (self.root / "vortex_ai/extra.py").write_bytes(b"UNEXPLAINED SOURCE\n")
        with self.assertRaisesRegex(ValueError, "retained installed binding differs"):
            runner._verify_retained_installation(self.root, self.expected)


if __name__ == "__main__":
    unittest.main()
