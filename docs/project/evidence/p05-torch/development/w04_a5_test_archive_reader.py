#!/usr/bin/env python3
"""Adversarial data-only tests for the trusted P05 framework archive reader."""

import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile


ROOT = Path(__file__).resolve().parent.parent / "AI-GPU"
SOURCE = ROOT / "docs/project/evidence/p05-torch/reviews/archive_reader.py"
spec = importlib.util.spec_from_file_location("trusted_p05_archive_reader", SOURCE)
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


class ArchiveReaderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="p05-archive-reader-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.path = self.root / "original.zip"

    def archive(self, rows, *, compression=zipfile.ZIP_DEFLATED, comment=b""):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.path, "w", compression=compression) as output:
                for name, raw in rows:
                    output.writestr(name, raw)
                output.comment = comment
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def raw_archive(self, raw):
        self.path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def test_identity_is_verified_before_zip_parsing(self):
        self.path.write_bytes(b"not a zip")
        with mock.patch.object(zipfile, "ZipFile", side_effect=AssertionError("must not parse")):
            with self.assertRaisesRegex(reader.ArchiveError, "SHA-256 differs"):
                reader.ArchiveReader(self.path, "0" * 64)

    def test_prefix_views_do_not_extract_or_execute_retained_code(self):
        marker = self.root / "executed"
        raw = ("from pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\n").encode()
        digest = self.archive([
            ("torch/report.json", b'{"outcome":"fail","elapsed":1.25}'),
            ("torch/artifacts/source/payload.py", raw),
            ("torch/python/report.json", b'{"observed":true}'),
            ("python/report.json", b'{"old":0}'),
        ])
        with reader.ArchiveReader(self.path, digest) as archive:
            view = archive.view("torch")
            self.assertEqual(view.json("report.json"), {"outcome": "fail", "elapsed": 1.25})
            self.assertEqual(view.subview("python").json("report.json"), {"observed": True})
            self.assertEqual(view.read("artifacts/source/payload.py"), raw)
            self.assertEqual(len(view.inventory()), 3)
            self.assertFalse(archive.receipt()["acceptance_claimed"])
            self.assertFalse(archive.receipt()["retained_code_executed"])
        self.assertFalse(marker.exists())
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["original.zip"])
        with self.assertRaisesRegex(reader.ArchiveError, "closed"):
            archive.files()

    def test_recorded_absolute_paths_never_require_live_host_paths(self):
        value = "/unavailable/github/runner/p05-torch/torch-work/venv/bin/python"
        with mock.patch.object(Path, "stat", side_effect=AssertionError("no live reads")):
            self.assertEqual(str(reader.recorded_absolute(value)), value)
        for bad in ("/", "relative", "/a/../b", "/a//b", "/a\\b"):
            with self.subTest(path=bad), self.assertRaises(reader.ArchiveError):
                reader.recorded_absolute(bad)

    def test_unsafe_names_cannot_escape_a_packet(self):
        for bad in ("../x", "/absolute", "a/../b", "a//b", "a/./b", "a\\b", "C:/escape", "a\x01b"):
            with self.subTest(path=bad):
                digest = self.archive([(bad, b"data")])
                with self.assertRaises(reader.ArchiveError):
                    reader.ArchiveReader(self.path, digest)

    def test_hidden_nul_filename_is_rejected(self):
        self.archive([("badXname", b"data")])
        raw = self.path.read_bytes().replace(b"badXname", b"bad\x00name")
        with self.assertRaisesRegex(reader.ArchiveError, "NUL"):
            reader.ArchiveReader(self.path, self.raw_archive(raw))

    def test_duplicate_and_file_directory_shadowing_are_rejected(self):
        cases = ([('a', b'1'), ('a', b'2')], [('a/', b''), ('a', b'1')],
                 [('a', b'1'), ('a/b', b'2')], [('a/b', b'2'), ('a', b'1')])
        for rows in cases:
            with self.subTest(rows=rows):
                digest = self.archive(rows)
                with self.assertRaises(reader.ArchiveError):
                    reader.ArchiveReader(self.path, digest)

    def test_symlink_and_special_members_are_rejected(self):
        for kind in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR, stat.S_IFSOCK):
            with self.subTest(kind=kind):
                info = zipfile.ZipInfo("member")
                info.create_system = 3
                info.external_attr = (kind | 0o600) << 16
                digest = self.archive([(info, b"payload")])
                with self.assertRaisesRegex(reader.ArchiveError, "symlink or special"):
                    reader.ArchiveReader(self.path, digest)

    def test_directory_payload_is_rejected(self):
        digest = self.archive([("folder/", b"hidden"), ("folder/a", b"data")])
        with self.assertRaises(reader.ArchiveError):
            reader.ArchiveReader(self.path, digest)

    def test_archive_path_symlinks_are_rejected(self):
        digest = self.archive([("report.json", b"{}")])
        link = self.root / "alias.zip"
        link.symlink_to(self.path)
        with self.assertRaisesRegex(reader.ArchiveError, "canonical"):
            reader.ArchiveReader(link, digest)

    def test_encryption_and_unreviewed_compression_are_rejected(self):
        digest = self.archive([("a", b"data")], compression=zipfile.ZIP_BZIP2)
        with self.assertRaisesRegex(reader.ArchiveError, "compression"):
            reader.ArchiveReader(self.path, digest)
        self.archive([("a", b"data")])
        raw = bytearray(self.path.read_bytes())
        central = raw.index(b"PK\x01\x02")
        struct.pack_into("<H", raw, central + 8, 1)
        struct.pack_into("<H", raw, 6, 1)
        digest = self.raw_archive(raw)
        with self.assertRaisesRegex(reader.ArchiveError, "encrypted"):
            reader.ArchiveReader(self.path, digest)

    def test_metadata_bounds_precede_decompression(self):
        digest = self.archive([("a", b"1234"), ("b", b"5678")])
        with mock.patch.object(reader, "EXPANDED_BYTES", 7):
            with self.assertRaisesRegex(reader.ArchiveError, "expanded"):
                reader.ArchiveReader(self.path, digest)
        with mock.patch.object(reader, "MEMBER_COUNT", 1):
            with self.assertRaisesRegex(reader.ArchiveError, "excessive-member"):
                reader.ArchiveReader(self.path, digest)
        with mock.patch.object(reader, "DIRECTORY_BYTES", 1):
            with self.assertRaisesRegex(reader.ArchiveError, "central directory"):
                reader.ArchiveReader(self.path, digest)
        raw = bytearray(self.path.read_bytes())
        central = raw.index(b"PK\x01\x02")
        struct.pack_into("<I", raw, central + 24, reader.MEMBER_BYTES + 1)
        with self.assertRaisesRegex(reader.ArchiveError, "member exceeds"):
            reader.ArchiveReader(self.path, self.raw_archive(raw))

    def test_multidisk_zip64_and_trailing_data_are_rejected(self):
        self.archive([("a", b"data")])
        original = self.path.read_bytes()
        for offset, value in ((4, 1), (8, 0xFFFF), (10, 0xFFFF)):
            raw = bytearray(original)
            end = raw.rfind(b"PK\x05\x06")
            struct.pack_into("<H", raw, end + offset, value)
            with self.subTest(offset=offset), self.assertRaises(reader.ArchiveError):
                reader.ArchiveReader(self.path, self.raw_archive(raw))
        with self.assertRaises(reader.ArchiveError):
            reader.ArchiveReader(self.path, self.raw_archive(original + b"trailing"))

    def test_member_crc_failure_is_not_a_successful_read(self):
        self.archive([("a", b"UNIQUE_PAYLOAD")], compression=zipfile.ZIP_STORED)
        raw = self.path.read_bytes().replace(b"UNIQUE_PAYLOAD", b"BROKEN_PAYLOAD")
        with reader.ArchiveReader(self.path, self.raw_archive(raw)) as archive:
            with self.assertRaisesRegex(reader.ArchiveError, "invalid retained member payload"):
                archive.read("a")
            self.assertEqual(archive.receipt()["read_files"], [])

    def test_failed_payload_reads_still_consume_the_read_budget(self):
        self.archive([("a", b"UNIQUE_PAYLOAD")], compression=zipfile.ZIP_STORED)
        raw = self.path.read_bytes().replace(b"UNIQUE_PAYLOAD", b"BROKEN_PAYLOAD")
        with reader.ArchiveReader(self.path, self.raw_archive(raw)) as archive:
            with mock.patch.object(reader, "READ_BYTES", len(b"UNIQUE_PAYLOAD")):
                with self.assertRaisesRegex(reader.ArchiveError, "invalid retained member payload"):
                    archive.read("a")
                with self.assertRaisesRegex(reader.ArchiveError, "aggregate"):
                    archive.read("a")

    def test_comments_are_explicitly_outside_the_reviewed_artifact_format(self):
        for comment in (b"plain comment", b"comment PK\x05\x06 still a comment"):
            digest = self.archive([("a", b"data")], comment=comment)
            with self.subTest(comment=comment), self.assertRaises(reader.ArchiveError):
                reader.ArchiveReader(self.path, digest)

    def test_member_and_aggregate_read_limits_are_enforced(self):
        digest = self.archive([("a", b"1234")])
        with reader.ArchiveReader(self.path, digest) as archive:
            with self.assertRaisesRegex(reader.ArchiveError, "requested read bound"):
                archive.read("a", limit=3)
            with self.assertRaises(reader.ArchiveError):
                archive.read("a", limit=True)
            with mock.patch.object(reader, "READ_BYTES", 8):
                self.assertEqual(archive.read("a"), b"1234")
                archive.identity("a")
                with self.assertRaisesRegex(reader.ArchiveError, "aggregate"):
                    archive.read("a")
        digest = self.archive([("empty", b"")])
        with reader.ArchiveReader(self.path, digest) as archive:
            with mock.patch.object(reader, "READ_ATTEMPTS", 1):
                self.assertEqual(archive.read("empty"), b"")
                with self.assertRaisesRegex(reader.ArchiveError, "aggregate"):
                    archive.read("empty")

    def test_descriptor_hash_size_path_and_bool_are_strict(self):
        digest = self.archive([("torch/a", b"x")])
        with reader.ArchiveReader(self.path, digest) as archive:
            view = archive.view("torch")
            row = view.identity("a")
            self.assertEqual(view.verified(row, "a"), b"x")
            for changed in ({**row, "sha256": "0" * 64}, {**row, "size_bytes": 2},
                            {**row, "size_bytes": True}, {**row, "path": "../a"},
                            {**row, "extra": 0}):
                with self.subTest(row=changed), self.assertRaises(reader.ArchiveError):
                    view.verified(changed)
            with self.assertRaises(reader.ArchiveError):
                view.verified(row, "different")

    def test_source_mutation_invalidates_read_and_final_identity(self):
        digest = self.archive([("a", b"data")])
        archive = reader.ArchiveReader(self.path, digest)
        self.path.write_bytes(self.path.read_bytes() + b"changed")
        with self.assertRaisesRegex(reader.ArchiveError, "changed"):
            archive.read("a")
        with self.assertRaisesRegex(reader.ArchiveError, "changed"):
            archive.close()
        self.assertTrue(archive._closed)

    def test_strict_json_rejects_ambiguous_and_unbounded_values(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":{"b":1,"b":2}}', b'NaN', b'Infinity',
                    b'1e999', b'"\xff"', b"9" * 65, b"[" * 65 + b"0" + b"]" * 65):
            with self.subTest(raw=raw[:80]), self.assertRaises(reader.ArchiveError):
                reader.strict_json(raw)
        for raw in (b'1.0', b'1e0'):
            with self.assertRaises(reader.ArchiveError):
                reader.strict_json(raw, integers_only=True)
        self.assertEqual(reader.strict_json(b'{"duration":1.25,"flag":true}'),
                         {"duration": 1.25, "flag": True})
        with self.assertRaises(reader.ArchiveError):
            reader.strict_json(b"[" + b"0," * 300000 + b"0]")


if __name__ == "__main__":
    unittest.main(verbosity=2)
