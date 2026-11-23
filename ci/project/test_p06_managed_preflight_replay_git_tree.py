# SPDX-License-Identifier: Apache-2.0
"""Source export must conserve the complete selected Git tree identity."""

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zlib

import p06_managed_preflight_source_export as exporter
from test_p06_managed_preflight_source_export import git


class SourceExportTreeClosureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="p06-git-tree-closure-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name).resolve() / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "--quiet")
        self.write("plain.cpp", b"plain source\n")
        self.write("nested/source.cpp", b"original nested source\n")
        self.commit()

    def write(self, name, body):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    def commit(self):
        git(self.repo, "add", "--all")
        git(self.repo, "commit", "--quiet", "-m", "tree fixture")
        self.revision = git(self.repo, "rev-parse", "HEAD").decode().strip()

    def reader(self):
        return exporter.GitObjects(self.repo, self.revision)

    def substitute_nested_tree(self):
        old_tree = git(self.repo, "rev-parse", self.revision + ":nested").decode().strip()
        replacement = b"different nested source\n"
        blob = git(self.repo, "hash-object", "-w", "--stdin", data=replacement).decode().strip()
        body = b"100644 source.cpp\0" + bytes.fromhex(blob)
        raw = b"tree " + str(len(body)).encode() + b"\0" + body
        self.assertNotEqual(hashlib.sha1(raw).hexdigest(), old_tree)
        # Only this disposable repository's loose object is altered.
        path = self.repo / ".git/objects" / old_tree[:2] / old_tree[2:]
        path.chmod(0o644)
        path.write_bytes(zlib.compress(raw))
        return blob, replacement

    def test_modified_nested_tree_bytes_cannot_keep_original_root_identity(self):
        root = git(self.repo, "rev-parse", self.revision + "^{tree}")
        blob, body = self.substitute_nested_tree()
        flat = git(self.repo, "ls-tree", "-r", "-z", "--full-tree", self.revision)
        self.assertIn(blob.encode() + b"\tnested/source.cpp\0", flat)
        self.assertEqual(git(self.repo, "cat-file", "blob", blob), body)
        self.assertEqual(git(self.repo, "rev-parse", self.revision + "^{tree}"), root)
        with self.assertRaisesRegex(exporter.ExportError, "selected root identity"):
            self.reader()

    def test_git_canonical_order_modes_and_shared_object_ids_are_supported(self):
        for name in ("a.b", "a0", "a/file.h", "a-/file.h", "other/copy.cpp",
                     "vendor/module.x", "vendor/module0/file.h"):
            self.write(name, b"plain source\n")
        self.write("run.sh", b"#!/bin/sh\nexit 0\n")
        (self.repo / "run.sh").chmod(0o755)
        (self.repo / "link.h").symlink_to("plain.cpp")
        git(self.repo, "add", "--all")
        git(self.repo, "update-index", "--add", "--cacheinfo",
            "160000," + self.revision + ",vendor/module")
        git(self.repo, "commit", "--quiet", "-m", "ordering and modes")
        self.revision = git(self.repo, "rev-parse", "HEAD").decode().strip()
        reader = self.reader()
        self.assertEqual(reader.tree_id,
                         git(self.repo, "rev-parse", self.revision + "^{tree}").decode().strip())
        self.assertEqual(reader.commands, 4)
        self.assertEqual(reader.bytes_read, 0)
        self.assertEqual(reader.entries["run.sh"]["mode"], "100755")
        self.assertEqual(reader.entries["link.h"]["mode"], "120000")
        self.assertEqual(reader.entries["vendor/module"]["mode"], "160000")
        self.assertEqual(reader.entries["plain.cpp"]["oid"], reader.entries["other/copy.cpp"]["oid"])
        self.assertEqual(git(self.repo, "rev-parse", self.revision + ":a"),
                         git(self.repo, "rev-parse", self.revision + ":a-"))
        self.assertEqual(reader.blob("other/copy.cpp"), b"plain source\n")

    def test_flat_inventory_order_does_not_change_its_tree_identity(self):
        reader = self.reader()
        flat = git(self.repo, "ls-tree", "-r", "-z", "--full-tree", self.revision)
        reversed_flat = b"\0".join(reversed(flat[:-1].split(b"\0"))) + b"\0"
        with mock.patch.object(reader, "run", return_value=reversed_flat):
            self.assertEqual(reader._tree(), reader.entries)

    def test_omitted_file_or_changed_mode_rejects_at_root_identity(self):
        reader = self.reader()
        flat = git(self.repo, "ls-tree", "-r", "-z", "--full-tree", self.revision)
        missing = flat.split(b"\0", 1)[1]
        changed_mode = flat.replace(b"100644 blob ", b"100755 blob ", 1)
        for raw in (missing, changed_mode):
            with self.subTest(raw=raw), mock.patch.object(reader, "run", return_value=raw):
                with self.assertRaisesRegex(exporter.ExportError, "selected root identity"):
                    reader._tree()

    def test_file_directory_prefix_collisions_reject_in_both_orders(self):
        reader = self.reader()
        oid = reader.entries["plain.cpp"]["oid"].encode()
        leaf = b"100644 blob " + oid + b"\ta\0"
        child = b"100644 blob " + oid + b"\ta/b.cpp\0"
        for raw in (leaf + child, child + leaf):
            with self.subTest(raw=raw), mock.patch.object(reader, "run", return_value=raw):
                with self.assertRaisesRegex(exporter.ExportError, "prefix collision"):
                    reader._tree()

    def test_implicit_directories_share_the_total_tree_entry_bound(self):
        reader = self.reader()
        self.assertEqual(len(reader.entries), 2)
        with mock.patch.object(exporter, "MAX_TREE_ENTRIES", 2):
            with self.assertRaisesRegex(exporter.ExportError, "directories exceed its entry bound"):
                reader._tree()

    def test_omitted_empty_directory_is_explicitly_unsupported(self):
        blob = git(self.repo, "rev-parse", self.revision + ":plain.cpp").decode().strip()
        empty = git(self.repo, "mktree", data=b"").decode().strip()
        entries = ("040000 tree " + empty + "\tempty\n100644 blob " + blob + "\tplain.cpp\n").encode()
        root = git(self.repo, "mktree", data=entries).decode().strip()
        self.revision = git(self.repo, "commit-tree", root, "-m", "empty directory").decode().strip()
        flat = git(self.repo, "ls-tree", "-r", "-z", "--full-tree", self.revision)
        self.assertNotIn(b"empty", flat)
        with self.assertRaisesRegex(exporter.ExportError, "empty trees are unsupported"):
            self.reader()

    def test_existing_maximum_path_depth_is_bounded_and_supported(self):
        name = "/".join(["d"] * 63 + ["leaf.h"])
        self.write(name, b"deep source\n")
        self.commit()
        reader = self.reader()
        self.assertEqual(reader.blob(name), b"deep source\n")
        self.write("extra/" + name, b"too deep\n")
        self.commit()
        with self.assertRaisesRegex(exporter.ExportError, "path is unsafe or exceeds its bound"):
            self.reader()


if __name__ == "__main__":
    unittest.main()
