# SPDX-License-Identifier: Apache-2.0
"""Exercise local extraction with explicitly synthetic locked archive fixtures."""

import copy
import hashlib
import io
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import p06_local_toolchain as local


class LocalToolchainTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p06-local-tools-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.archives = self.root / "archives"
        self.archives.mkdir()
        self.tools = self.root / "tools"
        self.entries = {}
        for component in local.COMPONENTS:
            entries = []
            for name, relative in local.NATIVE_TOOLS.items():
                if relative.split("/", 1)[0] == component:
                    mode = 0o644 if name.startswith(("libc64/", "libcrt64/")) else 0o755
                    entries.append((relative, "file", ("synthetic " + name + "\n").encode(), mode))
            self.entries[component] = entries
        llvm = self.entries["llvm-vortex"]
        llvm[:] = [row for row in llvm if row[0] not in ("llvm-vortex/bin/clang", "llvm-vortex/bin/clang++")]
        llvm += [("llvm-vortex/bin/clang-20", "file", b"synthetic clang\n", 0o755),
                 ("llvm-vortex/bin/clang", "symlink", "clang-20", 0o777),
                 ("llvm-vortex/bin/clang++", "symlink", "clang", 0o777)]
        libc = self.entries["libc64"]
        libc[:] = [row for row in libc if row[0] != "libc64/lib/libm.a"]
        libc.append(("libc64/lib/libm.a", "hardlink", "libc64/lib/libc.a", 0o644))
        self.manifest = {"repository": "vortexgpgpu/vortex-toolchain-prebuilt", "tag": "v3.0.2",
            "revision": "e3db4bcdf819a17f618ad9fc2472f8f7dea3192b", "os_bundle": "ubuntu/focal",
            "sha256": "a" * 64, "size_bytes": 123, "parts": []}
        self.make_archives()
        self.stack = [mock.patch.object(local, "_locked_manifest", side_effect=lambda: copy.deepcopy(self.manifest)),
                      mock.patch.object(local, "available_memory_bytes", return_value=8 * 1024**3),
                      mock.patch.object(local.shutil, "disk_usage", return_value=SimpleNamespace(free=32 * 1024**3))]
        for patch in self.stack:
            patch.start()
            self.addCleanup(patch.stop)

    def make_archives(self):
        self.manifest["parts"] = []
        for component, rows in self.entries.items():
            raw = io.BytesIO()
            with tarfile.open(fileobj=raw, mode="w:bz2") as archive:
                directories = {component}
                for name, _, _, _ in rows:
                    directories.update(str(path) for path in Path(name).parents
                                       if str(path) != "." and not str(path).startswith(".."))
                for name in sorted(directories):
                    item = tarfile.TarInfo(name)
                    item.type, item.mode = tarfile.DIRTYPE, 0o755
                    archive.addfile(item)
                for name, kind, value, mode in rows:
                    item = tarfile.TarInfo(name)
                    item.mode = mode
                    if kind == "file":
                        item.size = len(value)
                        archive.addfile(item, io.BytesIO(value))
                    else:
                        item.type = {"symlink": tarfile.SYMTYPE, "hardlink": tarfile.LNKTYPE,
                                     "fifo": tarfile.FIFOTYPE}[kind]
                        item.linkname = value
                        archive.addfile(item)
            body = raw.getvalue()
            relative = component + "/" + component + ".tar.bz2"
            path = self.archives / relative
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(body)
            self.manifest["parts"].append({"path": relative, "size_bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "git_blob_sha": hashlib.sha1(("blob " + str(len(body)) + "\0").encode() + body).hexdigest()})

    def provision(self):
        return local.provision(self.archives, self.tools)

    def test_provision_joins_actual_bytes_and_keeps_local_scope(self):
        receipt = self.provision()
        self.assertEqual(receipt["origin"], "local-pinned-archives")
        self.assertEqual(receipt["native_execution"], "not_run")
        self.assertTrue(all(receipt[name] is False for name in local.dependency.FALSE_CLAIMS))
        self.assertEqual(set(receipt["tools"]), set(local.NATIVE_TOOLS))
        self.assertTrue((self.tools / "llvm-vortex/bin/clang++").is_symlink())
        self.assertEqual(receipt["tools"]["clang++"]["resolved_path"], str(self.tools / "llvm-vortex/bin/clang-20"))
        self.assertEqual((self.tools / "libc64/lib/libm.a").read_bytes(), (self.tools / "libc64/lib/libc.a").read_bytes())
        for identity in receipt["tools"].values():
            body = Path(identity["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(body).hexdigest(), identity["sha256"])
            self.assertEqual(len(body), identity["size_bytes"])

    def test_metadata_reader_never_opens_producer_paths(self):
        receipt = self.provision()
        shutil.rmtree(self.archives)
        shutil.rmtree(self.tools)
        with mock.patch.object(Path, "open", side_effect=AssertionError("producer path opened")), \
             mock.patch.object(Path, "resolve", side_effect=AssertionError("producer path resolved")):
            review = local.validate_receipt(receipt)
        self.assertTrue(review["metadata_consistent"])
        self.assertFalse(review["archive_bytes_rehashed"])
        self.assertFalse(review["installed_bytes_rehashed"])
        self.assertFalse(review["retained_code_executed"])

    def test_existing_output_rejects_before_archive_work(self):
        self.tools.mkdir()
        marker = self.tools / "original"
        marker.write_bytes(b"preserve")
        with self.assertRaisesRegex(ValueError, "fresh output"):
            self.provision()
        self.assertEqual(marker.read_bytes(), b"preserve")

    def test_changed_archive_is_rejected_before_output_creation(self):
        part = self.manifest["parts"][0]
        path = self.archives / part["path"]
        body = bytearray(path.read_bytes())
        body[len(body) // 2] ^= 1
        path.write_bytes(body)
        with self.assertRaisesRegex(ValueError, "immutable lock"):
            self.provision()
        self.assertFalse(self.tools.exists())

    def test_archive_blob_mismatch_is_rejected(self):
        self.manifest["parts"][0]["git_blob_sha"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "immutable lock"):
            self.provision()
        self.assertFalse(self.tools.exists())

    def test_truncated_archive_is_rejected_before_output_creation(self):
        part = self.manifest["parts"][0]
        path = self.archives / part["path"]
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError, "size or type"):
            self.provision()
        self.assertFalse(self.tools.exists())

    def test_archive_symlink_is_rejected(self):
        part = self.manifest["parts"][0]
        path = self.archives / part["path"]
        real = path.with_name("original.bz2")
        path.rename(real)
        path.symlink_to(real.name)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.provision()
        self.assertFalse(self.tools.exists())

    def test_insufficient_disk_or_memory_never_creates_outputs(self):
        with mock.patch.object(local.shutil, "disk_usage", return_value=SimpleNamespace(free=15 * 1024**3 - 1)):
            with self.assertRaisesRegex(ValueError, "disk reserve"):
                self.provision()
        with mock.patch.object(local, "available_memory_bytes", return_value=4 * 1024**3 - 1):
            with self.assertRaisesRegex(ValueError, "4 GiB"):
                self.provision()
        self.assertFalse(self.tools.exists())

    def test_archive_path_traversal_rejects_without_outside_write(self):
        self.entries["libcrt64"].append(("libcrt64/../../outside", "file", b"escape", 0o644))
        self.make_archives()
        with self.assertRaisesRegex(ValueError, "safe relative"):
            self.provision()
        self.assertFalse((self.root / "outside").exists())

    def test_cross_component_link_rejects(self):
        self.entries["libcrt64"].append(("libcrt64/escape", "symlink", "../libc64/lib/libc.a", 0o777))
        self.make_archives()
        with self.assertRaisesRegex(ValueError, "escapes its component"):
            self.provision()
        self.assertFalse((self.tools / "libcrt64/escape").is_symlink())

    def test_absolute_link_rejects(self):
        self.entries["libcrt64"].append(("libcrt64/escape", "symlink", "/tmp/not-permitted", 0o777))
        self.make_archives()
        with self.assertRaises((ValueError, tarfile.FilterError)):
            self.provision()

    def test_device_and_fifo_entries_reject(self):
        self.entries["libcrt64"].append(("libcrt64/fifo", "fifo", "", 0o644))
        self.make_archives()
        with self.assertRaisesRegex(ValueError, "type is unsupported"):
            self.provision()
        self.assertFalse((self.tools / "libcrt64/fifo").exists())

    def test_link_cycle_rejects_before_links_are_created(self):
        self.entries["libcrt64"] += [("libcrt64/a", "symlink", "b", 0o777),
                                     ("libcrt64/b", "symlink", "a", 0o777)]
        self.make_archives()
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.provision()
        self.assertFalse((self.tools / "libcrt64/a").is_symlink())

    def test_missing_selected_tool_rejects(self):
        self.entries["llvm-vortex"] = [row for row in self.entries["llvm-vortex"] if not row[0].endswith("llvm-objdump")]
        self.make_archives()
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.provision()

    def test_non_executable_selected_tool_rejects(self):
        self.entries["llvm-vortex"] = [(name, kind, value, 0o644 if name.endswith("llvm-objdump") else mode)
                                      for name, kind, value, mode in self.entries["llvm-vortex"]]
        self.make_archives()
        with self.assertRaisesRegex(ValueError, "not executable"):
            self.provision()

    def test_member_and_expanded_byte_limits_reject(self):
        with mock.patch.dict(local.BUDGET, {"max_extracted_bytes": 1}):
            with self.assertRaisesRegex(ValueError, "extracted-byte"):
                self.provision()
        shutil.rmtree(self.tools)
        with mock.patch.dict(local.BUDGET, {"max_members": 1}):
            with self.assertRaisesRegex(ValueError, "member bound"):
                self.provision()

    def test_duplicate_member_rejects(self):
        self.entries["libcrt64"].append(self.entries["libcrt64"][0])
        self.make_archives()
        with self.assertRaisesRegex(ValueError, "duplicate members"):
            self.provision()

    def test_receipt_scope_inventory_and_tool_mutations_reject(self):
        original = self.provision()
        changes = [
            lambda value: value.update(GITHUB_RUN_ID="123"),
            lambda value: value.update(schema_version=True),
            lambda value: value.update(origin="github-cache"),
            lambda value: value.update(revision="b" * 40),
            lambda value: value.update(qualified=True),
            lambda value: value["parts"].pop(),
            lambda value: value.update(compressed_bytes=value["compressed_bytes"] + 1),
            lambda value: value["members"].reverse(),
            lambda value: value["members"].append(value["members"][-1]),
            lambda value: value.update(member_count=True),
            lambda value: value.update(extracted_regular_bytes=0),
            lambda value: value["tools"].pop("clang"),
            lambda value: value["tools"]["clang"].update(sha256="b" * 64),
            lambda value: value["tools"]["clang"].update(resolved_path="/elsewhere/clang"),
            lambda value: value["tools"]["clang"].update(resolved_path=value["tools_root"] + "/llvm-vortex/bin/clang++"),
            lambda value: value["tools"]["clang"].update(path=value["tools_root"] + "/other"),
            lambda value: value.update(tools_root="/tmp/../tools"),
        ]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                mutated = copy.deepcopy(original)
                change(mutated)
                with self.assertRaises(ValueError):
                    local.validate_receipt(mutated)

    def test_receipt_cannot_invent_children_below_an_archive_file(self):
        receipt = self.provision()
        receipt["members"].append({"path": "llvm-vortex/bin/clang-20/child", "kind": "file",
                                   "size_bytes": 0, "sha256": hashlib.sha256(b"").hexdigest(), "mode": 0o644})
        receipt["members"].sort(key=lambda row: row["path"])
        receipt["member_count"] += 1
        with self.assertRaisesRegex(ValueError, "non-directory archive member"):
            local.validate_receipt(receipt)


class RealToolchainLockTests(unittest.TestCase):
    def test_reviewed_native_archive_selection_is_exact(self):
        manifest = local._locked_manifest()
        parts = local._selected_parts(manifest)
        self.assertEqual(manifest["revision"], "e3db4bcdf819a17f618ad9fc2472f8f7dea3192b")
        self.assertEqual(len(parts), 15)
        self.assertEqual(sum(row["size_bytes"] for row in parts), 606992434)
        self.assertEqual({row["path"].split("/", 1)[0] for row in parts}, set(local.COMPONENTS))


if __name__ == "__main__":
    unittest.main()
