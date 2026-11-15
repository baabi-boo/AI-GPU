# SPDX-License-Identifier: Apache-2.0
"""Independent packet I/O checks with inert, temporary filesystem evidence."""

import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import baseline_packet_io as packet_io


class StrictJSONTests(unittest.TestCase):
    def test_accepts_utf8_objects_and_finite_numbers(self):
        document = {"name": "café", "value": -1.25e20,
                    "nested": {"list": [True, None, 17]}}
        self.assertEqual(packet_io.load_json_bytes(
            json.dumps(document, ensure_ascii=False).encode("utf-8")), document)

    def test_rejects_duplicate_fields_at_every_depth(self):
        for contents in (b'{"a":1,"a":2}', b'{"nested":{"a":1,"a":2}}',
                         b'{"list":[{"a":1,"\\u0061":2}]}'):
            with self.subTest(contents=contents), self.assertRaises(packet_io.PacketError):
                packet_io.load_json_bytes(contents)

    def test_rejects_nonfinite_constants_and_float_overflow(self):
        for token in (b"NaN", b"Infinity", b"-Infinity", b"1e400", b"-1e9999"):
            with self.subTest(token=token), self.assertRaises(packet_io.PacketError):
                packet_io.load_json_bytes(b'{"number":' + token + b"}")

    def test_rejects_invalid_utf8_and_bom(self):
        for contents in (b'{"x":"\xff"}', b'{"x":"\xc3"}',
                         b'{"x":"\xed\xa0\x80"}', b"\xef\xbb\xbf{}"):
            with self.subTest(contents=contents), self.assertRaises(packet_io.PacketError):
                packet_io.load_json_bytes(contents, "report.json")

    def test_requires_one_complete_top_level_object(self):
        for contents in (b"[]", b"null", b"true", b"1", b'"value"',
                         b"", b"{}{}", b'{"x":}', b'{"x":1,}'):
            with self.subTest(contents=contents), self.assertRaises(packet_io.PacketError):
                packet_io.load_json_bytes(contents)

    def test_requires_byte_input(self):
        for contents in ("{}", None, {}, 7):
            with self.subTest(contents=contents), self.assertRaises(packet_io.PacketError):
                packet_io.load_json_bytes(contents)

    def test_rejects_excessive_depth_as_packet_error(self):
        contents = b'{"deep":' + b"[" * 2048 + b"0" + b"]" * 2048 + b"}"
        with self.assertRaises(packet_io.PacketError):
            packet_io.load_json_bytes(contents)

    def test_brackets_and_escaped_quotes_in_strings_are_not_nesting(self):
        document = {"text": '[{\\"}]' * 200}
        self.assertEqual(packet_io.load_json_bytes(json.dumps(document).encode()), document)


@unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"),
                     "packet filesystem safety requires POSIX no-follow support")
class FilesystemFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / "packet"
        self.root.mkdir()

    def write_member(self, relative, contents=b"evidence\n"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return path

    def reader(self, **limits):
        return self.enterContext(packet_io.PacketReader(self.root, **limits))

    def identity(self, relative, contents):
        return {"path": relative, "sha256": hashlib.sha256(contents).hexdigest(),
                "size_bytes": len(contents)}


class PacketReaderTests(FilesystemFixture):
    def test_reads_exact_bytes_and_streams_the_same_identity(self):
        contents = bytes(range(256)) * 513 + b"tail"
        path = self.write_member("logs/result.bin", contents)
        reader = self.reader()
        self.assertEqual(reader.read_bytes("logs/result.bin"), contents)
        self.assertEqual(reader.identity("logs/result.bin"),
                         self.identity("logs/result.bin", contents))
        self.assertIsNone(reader.recheck())
        self.assertEqual(path.read_bytes(), contents)

    def test_read_json_uses_strict_parser(self):
        self.write_member("valid.json", b'{"ok":true}')
        self.write_member("duplicate.json", b'{"a":1,"a":2}')
        self.write_member("nonfinite.json", b'{"a":1e400}')
        reader = self.reader()
        self.assertEqual(reader.read_json("valid.json"), {"ok": True})
        for name in ("duplicate.json", "nonfinite.json"):
            with self.subTest(name=name), self.assertRaises(packet_io.PacketError):
                reader.read_json(name)

    def test_rejects_noncanonical_and_unbounded_member_paths(self):
        self.write_member("safe")
        self.write_member("nested/safe")
        names = ("", ".", "..", "./safe", "nested/../safe", "../safe",
                 str(self.root / "safe"), "nested//safe", "safe/", "nested\\safe",
                 "C:safe", "C:/safe", "bad\x00name", "bad\nname", "bad\x7fname",
                 "bad\ud800name", "x" * 256, "/".join(["a"] * 129), "x" * 4097,
                 b"safe", Path("safe"))
        reader = self.reader()
        for name in names:
            with self.subTest(name=repr(name)), self.assertRaises(packet_io.PacketError):
                reader.read_bytes(name)
        self.assertEqual(reader.inventory(), [])
        self.assertEqual(reader.read_bytes("nested/safe"), b"evidence\n")

    def test_rejects_symlink_members_even_when_the_target_is_contained(self):
        target = self.write_member("target")
        outside = self.base / "outside"
        outside.write_bytes(b"external")
        for name, destination in (("contained", "target"), ("external", outside),
                                  ("dangling", "missing")):
            (self.root / name).symlink_to(destination)
        reader = self.reader()
        for name in ("contained", "external", "dangling"):
            with self.subTest(name=name), self.assertRaises(packet_io.PacketError):
                reader.read_bytes(name)
        self.assertEqual(target.read_bytes(), b"evidence\n")
        self.assertEqual(outside.read_bytes(), b"external")

    def test_rejects_member_symlink_ancestor_with_contained_target(self):
        self.write_member("real/member")
        (self.root / "alias").symlink_to("real", target_is_directory=True)
        with self.assertRaises(packet_io.PacketError):
            self.reader().identity("alias/member")

    def test_rejects_root_symlink_and_symlink_ancestor(self):
        self.write_member("subdirectory/member")
        alias = self.base / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        for root in (alias, alias / "subdirectory"):
            with self.subTest(root=root), self.assertRaises(packet_io.PacketError):
                with packet_io.PacketReader(root):
                    pass

    def test_missing_and_non_directory_roots_are_packet_errors(self):
        file_root = self.base / "file"
        file_root.write_bytes(b"file")
        for root in (self.base / "missing", file_root, "", b"bytes-root"):
            with self.subTest(root=root), self.assertRaises(packet_io.PacketError):
                with packet_io.PacketReader(root):
                    pass

    def test_missing_and_directory_members_are_rejected(self):
        (self.root / "directory").mkdir()
        reader = self.reader()
        for name in ("missing", "directory"):
            with self.subTest(name=name), self.assertRaises(packet_io.PacketError):
                reader.read_bytes(name)

    def test_fifo_and_regular_to_fifo_race_do_not_block(self):
        os.mkfifo(self.root / "pipe")
        self.write_member("raced")
        # A child timeout bounds a regression that accidentally opens a FIFO in blocking mode.
        script = """
import os
import sys
from pathlib import Path
from unittest import mock
sys.path.insert(0, sys.argv[1])
import baseline_packet_io as packet_io
root = Path(sys.argv[2])
with packet_io.PacketReader(root) as reader:
    for method in (reader.read_bytes, reader.identity, reader.read_json):
        try:
            method("pipe")
        except packet_io.PacketError:
            pass
        else:
            raise AssertionError("FIFO accepted")
    real_stat = os.stat
    changed = False
    def replace_with_fifo(path, *args, **kwargs):
        global changed
        info = real_stat(path, *args, **kwargs)
        if path == "raced" and not changed:
            changed = True
            (root / "raced").unlink()
            os.mkfifo(root / "raced")
        return info
    with mock.patch.object(packet_io.os, "stat", side_effect=replace_with_fifo):
        try:
            reader.read_bytes("raced")
        except packet_io.PacketError:
            pass
        else:
            raise AssertionError("raced FIFO accepted")
    assert changed
"""
        result = subprocess.run(
            [sys.executable, "-c", script, str(Path(packet_io.__file__).resolve().parent),
             str(self.root)], capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_byte_limit_rejects_before_reading_file_contents(self):
        self.write_member("large", b"12345")
        reader = self.reader()
        with mock.patch.object(packet_io.os, "read", side_effect=AssertionError("read called")):
            with self.assertRaises(packet_io.PacketError):
                reader.read_bytes("large", limit=4)
        self.assertEqual(reader.inventory(), [])
        self.assertEqual(reader.read_bytes("large", limit=5), b"12345")

    def test_unique_budgets_allow_rereads_and_inventory_is_sorted(self):
        self.write_member("z", b"z")
        self.write_member("a", b"aa")
        self.write_member("extra", b"e")
        reader = self.reader(max_total_bytes=3, max_files=2)
        self.assertEqual(reader.read_bytes("z"), b"z")
        self.assertEqual(reader.read_bytes("a"), b"aa")
        self.assertEqual(reader.read_bytes("z"), b"z")
        self.assertEqual(reader.identity("a"), self.identity("a", b"aa"))
        self.assertIsNone(reader.recheck())
        expected = [self.identity("a", b"aa"), self.identity("z", b"z")]
        self.assertEqual(reader.inventory(), expected)
        with self.assertRaises(packet_io.PacketError):
            reader.read_bytes("extra")
        self.assertEqual(reader.inventory(), expected)

    def test_total_bytes_and_file_count_are_independent_limits(self):
        self.write_member("first", b"abc")
        self.write_member("second", b"de")
        self.write_member("empty", b"")
        by_size = self.reader(max_total_bytes=4, max_files=3)
        by_size.read_bytes("first")
        with self.assertRaises(packet_io.PacketError):
            by_size.read_bytes("second")
        self.assertEqual(by_size.read_bytes("empty"), b"")
        by_count = self.reader(max_total_bytes=100, max_files=1)
        by_count.read_bytes("empty")
        with self.assertRaises(packet_io.PacketError):
            by_count.read_bytes("first")

    def test_zero_byte_budget_accepts_only_empty_files(self):
        self.write_member("empty", b"")
        self.write_member("nonempty", b"x")
        reader = self.reader(max_total_bytes=0, max_files=1)
        self.assertEqual(reader.read_bytes("empty", limit=0), b"")
        self.assertEqual(reader.identity("empty", limit=0), self.identity("empty", b""))
        with self.assertRaises(packet_io.PacketError):
            reader.read_bytes("nonempty")
        with self.assertRaises(packet_io.PacketError):
            self.reader(max_files=0).read_bytes("empty")

    def test_rejects_invalid_budget_types_and_bounds(self):
        for argument, invalid in (("max_total_bytes", (-1, True, 1.5, "4", 2**63)),
                                  ("max_files", (-1, True, 1.5, "4", 2**63))):
            for value in invalid:
                with self.subTest(argument=argument, value=value):
                    with self.assertRaises(packet_io.PacketError):
                        with packet_io.PacketReader(self.root, **{argument: value}):
                            pass
        self.write_member("member")
        reader = self.reader()
        for limit in (-1, True, 1.5, "4", 2**63):
            with self.subTest(limit=limit), self.assertRaises(packet_io.PacketError):
                reader.read_bytes("member", limit=limit)

    def test_returned_identities_cannot_mutate_recorded_inventory(self):
        self.write_member("member", b"bytes")
        reader = self.reader()
        record = reader.identity("member")
        record["sha256"] = "forged"
        inventory = reader.inventory()
        inventory[0]["path"] = "forged"
        inventory.clear()
        self.assertEqual(reader.inventory(), [self.identity("member", b"bytes")])
        self.assertIsNone(reader.recheck())

    def test_repeated_read_rejects_same_size_content_drift_with_restored_mtime(self):
        path = self.write_member("member", b"before")
        reader = self.reader()
        reader.read_bytes("member")
        original = path.stat()
        path.write_bytes(b"after!")
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
        with self.assertRaises(packet_io.PacketError):
            reader.read_bytes("member")

    def test_recheck_rejects_inode_replacement_even_with_identical_contents(self):
        path = self.write_member("member", b"identical")
        reader = self.reader()
        reader.identity("member")
        original = path.stat()
        replacement = self.write_member("replacement", b"identical")
        os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
        os.replace(replacement, path)
        with self.assertRaises(packet_io.PacketError):
            reader.recheck()

    def test_recheck_rejects_deleted_or_symlink_replaced_member(self):
        for replacement in ("missing", "symlink"):
            with self.subTest(replacement=replacement):
                path = self.write_member("member", b"original")
                with packet_io.PacketReader(self.root) as reader:
                    reader.read_bytes("member")
                    path.unlink()
                    if replacement == "symlink":
                        self.write_member("target", b"original")
                        path.symlink_to("target")
                    with self.assertRaises(packet_io.PacketError):
                        reader.recheck()

    def test_growth_or_truncation_during_read_is_rejected(self):
        for contents in (b"grown beyond the original", b""):
            with self.subTest(contents=contents):
                path = self.write_member("member", b"original")
                with packet_io.PacketReader(self.root) as reader:
                    real_read = os.read
                    changed = False

                    def alter_before_read(descriptor, size):
                        nonlocal changed
                        if not changed:
                            changed = True
                            path.write_bytes(contents)
                        return real_read(descriptor, size)

                    with mock.patch.object(packet_io.os, "read", side_effect=alter_before_read):
                        with self.assertRaises(packet_io.PacketError):
                            reader.read_bytes("member")
                    self.assertTrue(changed)
                    self.assertEqual(reader.inventory(), [])

    def test_member_directory_replacement_during_read_is_rejected(self):
        self.write_member("nested/member", b"original")
        reader = self.reader()
        real_read = os.read
        changed = False

        def replace_directory(descriptor, size):
            nonlocal changed
            chunk = real_read(descriptor, size)
            if not changed:
                changed = True
                (self.root / "nested").rename(self.root / "retired")
                self.write_member("nested/member", b"original")
            return chunk

        with mock.patch.object(packet_io.os, "read", side_effect=replace_directory):
            with self.assertRaises(packet_io.PacketError):
                reader.read_bytes("nested/member")
        self.assertTrue(changed)

    def test_root_replacement_with_directory_or_symlink_is_rejected(self):
        for replacement in ("directory", "symlink"):
            with self.subTest(replacement=replacement):
                root = self.base / replacement
                root.mkdir()
                (root / "member").write_bytes(b"original")
                with packet_io.PacketReader(root) as reader:
                    reader.read_bytes("member")
                    retired = self.base / (replacement + "-retired")
                    root.rename(retired)
                    if replacement == "directory":
                        root.mkdir()
                        (root / "member").write_bytes(b"original")
                    else:
                        root.symlink_to(retired, target_is_directory=True)
                    with self.assertRaises(packet_io.PacketError):
                        reader.read_bytes("member")
                    with self.assertRaises(packet_io.PacketError):
                        reader.recheck()

    def test_root_ancestor_replacement_is_rejected_even_before_first_read(self):
        ancestor = self.base / "ancestor"
        root = ancestor / "packet"
        root.mkdir(parents=True)
        with packet_io.PacketReader(root) as reader:
            ancestor.rename(self.base / "retired-ancestor")
            root.mkdir(parents=True)
            with self.assertRaises(packet_io.PacketError):
                reader.recheck()

    def test_close_is_idempotent_and_closed_reader_rejects_access(self):
        self.write_member("member")
        reader = self.reader()
        reader.close()
        reader.close()
        with self.assertRaises(packet_io.PacketError):
            reader.read_bytes("member")
        with self.assertRaises(packet_io.PacketError):
            reader.recheck()


class ExclusiveWriterTests(FilesystemFixture):
    def test_creates_exact_private_output_in_existing_directory(self):
        path = self.base / "manifest.json"
        contents = b'{"manifest":true}\n\x00'
        packet_io.write_bytes_exclusive(path, contents)
        self.assertEqual(path.read_bytes(), contents)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o077, 0)
        self.assertTrue(stat.S_ISREG(path.stat().st_mode))

    def test_empty_output_is_created(self):
        path = self.base / "empty"
        packet_io.write_bytes_exclusive(path, b"")
        self.assertEqual(path.read_bytes(), b"")

    def test_existing_file_is_never_overwritten(self):
        path = self.base / "existing"
        path.write_bytes(b"preserve")
        before = path.stat()
        with self.assertRaises(packet_io.PacketError):
            packet_io.write_bytes_exclusive(path, b"replacement")
        self.assertEqual(path.read_bytes(), b"preserve")
        after = path.stat()
        self.assertEqual((after.st_ino, after.st_mtime_ns),
                         (before.st_ino, before.st_mtime_ns))

    def test_existing_symlinks_never_follow_or_replace_their_targets(self):
        target = self.base / "target"
        target.write_bytes(b"preserve")
        for name, destination in (("live", target), ("dangling", self.base / "missing")):
            path = self.base / name
            path.symlink_to(destination)
            with self.subTest(name=name), self.assertRaises(packet_io.PacketError):
                packet_io.write_bytes_exclusive(path, b"replacement")
            self.assertTrue(path.is_symlink())
            self.assertEqual(os.readlink(path), str(destination))
        self.assertEqual(target.read_bytes(), b"preserve")
        self.assertFalse((self.base / "missing").exists())

    def test_symlink_output_ancestor_is_rejected(self):
        alias = self.base / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(packet_io.PacketError):
            packet_io.write_bytes_exclusive(alias / "manifest", b"bytes")
        self.assertFalse((self.root / "manifest").exists())

    def test_missing_parent_and_nonbytes_output_fail_without_creating_files(self):
        with self.assertRaises(packet_io.PacketError):
            packet_io.write_bytes_exclusive(self.base / "missing" / "output", b"bytes")
        for contents in ("text", bytearray(b"bytes"), None):
            with self.subTest(contents=contents), self.assertRaises(packet_io.PacketError):
                packet_io.write_bytes_exclusive(self.base / "output", contents)
        self.assertFalse((self.base / "missing").exists())
        self.assertFalse((self.base / "output").exists())

    def test_partial_writes_are_completed(self):
        path = self.base / "output"
        real_write = os.write

        def write_prefix(descriptor, data):
            return real_write(descriptor, data[:3])

        with mock.patch.object(packet_io.os, "write", side_effect=write_prefix):
            packet_io.write_bytes_exclusive(path, b"all of the bytes")
        self.assertEqual(path.read_bytes(), b"all of the bytes")

    def test_write_failure_preserves_partial_output_and_prevents_retry_overwrite(self):
        path = self.base / "output"
        real_write = os.write
        calls = 0

        def run_out_of_space(descriptor, data):
            nonlocal calls
            calls += 1
            if calls == 1:
                return real_write(descriptor, data[:4])
            raise OSError(errno.ENOSPC, "injected output exhaustion")

        with mock.patch.object(packet_io.os, "write", side_effect=run_out_of_space):
            with self.assertRaises(packet_io.PacketError):
                packet_io.write_bytes_exclusive(path, b"partial output")
        self.assertEqual(path.read_bytes(), b"part")
        with self.assertRaises(packet_io.PacketError):
            packet_io.write_bytes_exclusive(path, b"retry")
        self.assertEqual(path.read_bytes(), b"part")

    def test_write_without_progress_fails_and_preserves_created_file(self):
        path = self.base / "output"
        with mock.patch.object(packet_io.os, "write", return_value=0):
            with self.assertRaises(packet_io.PacketError):
                packet_io.write_bytes_exclusive(path, b"bytes")
        self.assertEqual(path.read_bytes(), b"")

    def test_fsync_failure_is_reported_and_written_output_is_preserved(self):
        path = self.base / "output"
        with mock.patch.object(packet_io.os, "fsync", side_effect=OSError(errno.EIO, "injected")):
            with self.assertRaises(packet_io.PacketError):
                packet_io.write_bytes_exclusive(path, b"written")
        self.assertEqual(path.read_bytes(), b"written")

    def test_output_parent_replacement_during_write_is_rejected(self):
        parent = self.base / "destination"
        parent.mkdir()
        retired = self.base / "retired-destination"
        real_write = os.write
        changed = False

        def replace_parent(descriptor, data):
            nonlocal changed
            count = real_write(descriptor, data)
            if not changed:
                changed = True
                parent.rename(retired)
                parent.mkdir()
            return count

        with mock.patch.object(packet_io.os, "write", side_effect=replace_parent):
            with self.assertRaises(packet_io.PacketError):
                packet_io.write_bytes_exclusive(parent / "output", b"preserved")
        self.assertEqual((retired / "output").read_bytes(), b"preserved")
        self.assertFalse((parent / "output").exists())


if __name__ == "__main__":
    unittest.main()
