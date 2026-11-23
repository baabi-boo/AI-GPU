# SPDX-License-Identifier: Apache-2.0
"""Independent archive-link and streaming mutation controls with tiny fixtures."""

import copy
import hashlib
from pathlib import Path
import unittest
from unittest import mock

import p06_local_toolchain as local
import test_p06_local_toolchain as fixtures


class LocalToolchainReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LocalToolchainTests(
            methodName="test_provision_joins_actual_bytes_and_keeps_local_scope")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_parent_segments_after_a_symbolic_prefix_cannot_escape_output(self):
        f = self.fixture
        outside = f.root / "outside"
        outside.write_bytes(b"outside sentinel")
        f.entries["libcrt64"] += [
            ("libcrt64/outside", "file", b"internal decoy", 0o644),
            ("libcrt64/dir/alias", "symlink", "..", 0o777),
            ("libcrt64/escape", "symlink", "dir/alias/../../outside", 0o777),
        ]
        f.make_archives()
        with self.assertRaises(ValueError):
            f.provision()
        self.assertEqual(outside.read_bytes(), b"outside sentinel")

    def test_inert_reader_rejects_the_same_symbolic_prefix_escape(self):
        f = self.fixture
        receipt = f.provision()
        body = b"internal decoy"
        receipt["members"] += [
            {"path": "libcrt64/dir", "kind": "directory"},
            {"path": "libcrt64/dir/alias", "kind": "symlink", "target": ".."},
            {"path": "libcrt64/escape", "kind": "symlink", "target": "dir/alias/../../outside"},
            {"path": "libcrt64/outside", "kind": "file", "mode": 0o644,
             "size_bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()},
        ]
        receipt["members"].sort(key=lambda row: row["path"])
        receipt["member_count"] += 4
        receipt["extracted_regular_bytes"] += len(body)
        with mock.patch.object(Path, "open", side_effect=AssertionError("producer path opened")), \
             mock.patch.object(Path, "resolve", side_effect=AssertionError("producer path resolved")):
            with self.assertRaises(ValueError):
                local.validate_receipt(receipt)

    def test_internal_parent_segments_follow_the_symbolic_prefix_first(self):
        f = self.fixture
        f.entries["libcrt64"] += [
            ("libcrt64/aliases/back", "symlink", "../lib/baremetal", 0o777),
            ("libcrt64/valid", "symlink",
             "aliases/back/../baremetal/libclang_rt.builtins-riscv64.a", 0o777),
        ]
        f.make_archives()
        receipt = f.provision()
        expected = f.tools / "libcrt64/lib/baremetal/libclang_rt.builtins-riscv64.a"
        self.assertEqual((f.tools / "libcrt64/valid").resolve(strict=True), expected)
        self.assertEqual((f.tools / "libcrt64/valid").read_bytes(), expected.read_bytes())
        self.assertTrue(local.validate_receipt(receipt)["metadata_consistent"])
        # Descendants establish directories even if the tar omitted their entries.
        implicit = copy.deepcopy(receipt)
        implicit["members"] = [row for row in implicit["members"] if row["path"] not in
                               ("libcrt64/lib", "libcrt64/lib/baremetal")]
        implicit["member_count"] = len(implicit["members"])
        with mock.patch.object(Path, "open", side_effect=AssertionError("producer path opened")), \
             mock.patch.object(Path, "resolve", side_effect=AssertionError("producer path resolved")):
            self.assertTrue(local.validate_receipt(implicit)["metadata_consistent"])

    def test_parent_segments_cannot_hide_a_symbolic_cycle(self):
        f = self.fixture
        f.entries["libcrt64"] += [
            ("libcrt64/dir/libcrt64/loop", "file", b"cycle decoy", 0o644),
            ("libcrt64/dir/alias", "symlink", "..", 0o777),
            ("libcrt64/loop", "symlink", "dir/alias/../libcrt64/loop", 0o777),
        ]
        f.make_archives()
        with self.assertRaises(ValueError):
            f.provision()

    def test_inert_reader_rejects_a_missing_directory_before_parent_segments(self):
        f = self.fixture
        receipt = f.provision()
        target = "missing/../lib/baremetal/libclang_rt.builtins-riscv64.a"
        path = f.tools / "libcrt64/invalid"
        path.symlink_to(target)
        with self.assertRaises(FileNotFoundError):
            path.resolve(strict=True)
        receipt["members"].append(
            {"path": "libcrt64/invalid", "kind": "symlink", "target": target})
        receipt["members"].sort(key=lambda row: row["path"])
        receipt["member_count"] += 1
        with mock.patch.object(Path, "open", side_effect=AssertionError("producer path opened")), \
             mock.patch.object(Path, "resolve", side_effect=AssertionError("producer path resolved")):
            with self.assertRaises(ValueError):
                local.validate_receipt(receipt)

    def test_stream_rechecks_bytes_changed_after_the_initial_part_check(self):
        f = self.fixture
        expected = copy.deepcopy(f.manifest["parts"][0])
        path = f.archives / expected["path"]
        local._part(path, expected)
        body = bytearray(path.read_bytes())
        body[-1] ^= 1
        path.write_bytes(body)
        with local._Parts(f.archives, [expected]) as stream:
            with self.assertRaisesRegex(ValueError, "changed during extraction"):
                while stream.read(7):
                    pass


if __name__ == "__main__":
    unittest.main()
