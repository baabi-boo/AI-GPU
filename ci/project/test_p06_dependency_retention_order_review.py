# SPDX-License-Identifier: Apache-2.0
"""Independent regressions for the retained packet's POSIX-path ordering."""

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import p06_dependency_build as build
import p06_dependency_contract as contract


class DependencyRetentionOrderingReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p06-retention-order-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.producer = object.__new__(build.Builder)
        self.producer.output = self.root

    def put(self, name, body):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return path

    def test_prefix_collisions_follow_the_reader_posix_string_order(self):
        names = [
            "sources/ramulator/src/dram/lambdas.h",
            "sources/ramulator/src/dram/lambdas/action.h",
            "sources/ramulator/src/dram/lambdas/rowopen.h",
            "sources/softfloat/source/8086-SSE/specialize.h",
            "sources/softfloat/source/8086/specialize.h",
            "sources/softfloat/source/ARM-VFPv2-defaultNaN/specialize.h",
            "sources/softfloat/source/ARM-VFPv2/specialize.h",
        ]
        expected = []
        for name in reversed(names):
            body = ("retained input: " + name + "\n").encode()
            self.put(name, body)
            expected.append({"path": name, "sha256": hashlib.sha256(body).hexdigest(),
                             "size_bytes": len(body)})
        self.put("report.json", b"the report does not inventory itself\n")
        (self.root / "empty-directory").mkdir()
        rows = self.producer.retained_inventory()
        self.assertEqual([row["path"] for row in rows], names)
        self.assertEqual(rows, list(reversed(expected)))
        self.assertNotEqual(names, [str(path) for path in sorted(map(Path, names))],
                            "the regression must distinguish Path and POSIX-string order")

    def test_retained_inventory_still_rejects_symlinks(self):
        target = self.put("source.h", b"selected source\n")
        (self.root / "alias.h").symlink_to(target)
        with self.assertRaisesRegex(ValueError, "contains a symlink"):
            self.producer.retained_inventory()

    def test_retained_inventory_still_enforces_its_total_byte_bound(self):
        self.put("source.h", b"four")
        with mock.patch.object(contract, "MAX_PACKET_BYTES", 3):
            with self.assertRaisesRegex(ValueError, "exceeds its byte bound"):
                self.producer.retained_inventory()


if __name__ == "__main__":
    unittest.main()
