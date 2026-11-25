# SPDX-License-Identifier: Apache-2.0
"""Focused inert ZIP boundary and complete-byte integrity checks."""

import hashlib
import io
import os
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile
import zlib

import governance_replay_archive as reader


class _Nonseekable(io.BytesIO):
    def seek(self, *arguments):
        raise io.UnsupportedOperation("seek")


class GovernanceReplayArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="governance-zip-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.path = self.base / "governance.zip"

    def write(self, entries=None, *, method=zipfile.ZIP_DEFLATED, descriptor=False,
              attributes=(stat.S_IFREG | 0o644) << 16 | 0x20, creator=3):
        output = _Nonseekable() if descriptor else io.BytesIO()
        if entries is None:
            entries = [("run/summary.json", b'{"status":"completed"}\n')]
        with warnings.catch_warnings(), zipfile.ZipFile(output, "w") as archive:
            warnings.simplefilter("ignore", UserWarning)
            for name, body in entries:
                item = zipfile.ZipInfo(name)
                item.create_system = creator
                item.external_attr = attributes
                item.compress_type = method
                archive.writestr(item, body)
        self.path.write_bytes(output.getvalue())
        return output.getvalue()

    def reject(self, body=None):
        if body is not None:
            self.path.write_bytes(body)
        with self.assertRaises(reader.ArchiveError):
            reader.read_archive(self.path)

    @staticmethod
    def central(body):
        return struct.unpack_from("<I", body, len(body) - 6)[0]

    def mutate(self, body, offset, code, value):
        changed = bytearray(body)
        struct.pack_into("<" + code, changed, offset, value)
        self.reject(changed)

    def raw_zip(self, *, plain, compressed, size=None, method=8, gap=b""):
        name = b"run/events.jsonl"
        size = len(plain) if size is None else size
        crc = zlib.crc32(plain)
        local = struct.pack("<4s5H3I2H", b"PK\x03\x04", 20, 0, method, 0, 0,
                            crc, len(compressed), size, len(name), 0) + name + compressed + gap
        central = struct.pack("<4s6H3I5H2I", b"PK\x01\x02", 3 << 8 | 20, 20, 0,
                              method, 0, 0, crc, len(compressed), size, len(name), 0, 0,
                              0, 0, (stat.S_IFREG | 0o644) << 16, 0) + name
        end = struct.pack("<4s4H2IH", b"PK\x05\x06", 0, 0, 1, 1,
                          len(central), len(local), 0)
        self.path.write_bytes(local + central + end)

    @staticmethod
    def deflate(body):
        encoder = zlib.compressobj(wbits=-15)
        return encoder.compress(body) + encoder.flush()

    def test_reads_workflow_attributes_and_signed_descriptors(self):
        entries = [("run/summary.json", b"{}\n"), ("run/events.jsonl", b"event\n" * 2000)]
        original = self.write(entries, descriptor=True)
        result = reader.read_archive(self.path)
        self.assertEqual(result["members"], dict(entries))
        self.assertEqual(result["archive"], {"bytes": len(original),
                                            "sha256": hashlib.sha256(original).hexdigest()})
        self.assertEqual(result["member_count"], 2)
        self.assertEqual(result["total_uncompressed_bytes"], sum(len(body) for _, body in entries))
        self.assertEqual(result["total_compressed_bytes"], sum(
            row["compressed_bytes"] for row in result["member_identities"].values()))
        for name, body in entries:
            self.assertEqual(result["member_identities"][name]["bytes"], len(body))
            self.assertEqual(result["member_identities"][name]["sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(self.path.read_bytes(), original)

    def test_stored_empty_and_permission_only_members_are_regular(self):
        for method in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            for attributes, creator in ((0o600 << 16, 3), (0x20, 0)):
                with self.subTest(method=method, attributes=attributes, creator=creator):
                    self.write([("run/empty.log", b"")], method=method,
                               attributes=attributes, creator=creator)
                    self.assertEqual(reader.read_archive(self.path)["members"], {"run/empty.log": b""})

    def test_selected_members_still_hash_unretained_log_and_do_not_execute(self):
        log = b"raise AssertionError('must remain inert')\n" * 10000
        self.write([("run/summary.json", b"{}"), ("logs/governance.log", log)])
        with mock.patch.object(zipfile.ZipFile, "read", side_effect=AssertionError("whole member read")), \
             mock.patch.object(zipfile.ZipFile, "extract", side_effect=AssertionError("extraction")), \
             mock.patch.object(zipfile.ZipFile, "extractall", side_effect=AssertionError("extraction")), \
             mock.patch.object(os, "system", side_effect=AssertionError("execution")):
            result = reader.read_archive(self.path, retain=("run/summary.json",))
        self.assertEqual(result["members"], {"run/summary.json": b"{}"})
        self.assertEqual(result["member_identities"]["logs/governance.log"]["sha256"],
                         hashlib.sha256(log).hexdigest())

    def test_empty_retention_hashes_all_members(self):
        self.write()
        result = reader.read_archive(self.path, retain=())
        self.assertEqual(result["members"], {})
        self.assertEqual(set(result["member_identities"]), {"run/summary.json"})

    def test_zip64_end_records_are_rejected_before_parser_allocation(self):
        original = self.write()
        end = list(struct.unpack("<4s4H2IH", original[-22:]))
        directory_size, directory_start = end[5:7]
        for declared_size in (directory_size, reader.MAX_DIRECTORY_BYTES + 1):
            with self.subTest(declared_size=declared_size):
                extension = struct.pack("<4sQ2H2L4Q", b"PK\x06\x06", 44, 45, 45,
                                        0, 0, 1, 1, declared_size, directory_start)
                extension += struct.pack("<4sLQL", b"PK\x06\x07", 0, len(original) - 22, 1)
                ordinary = list(end)
                ordinary[5] += len(extension)
                self.path.write_bytes(original[:-22] + extension + struct.pack("<4s4H2IH", *ordinary))
                with mock.patch.object(reader.zipfile, "ZipFile") as parser:
                    self.reject()
                    parser.assert_not_called()

    def test_retention_must_be_bounded_and_exist(self):
        self.write()
        for retain in ("run/summary.json", 5, ("missing",), ("../escape",),
                       ["run/summary.json"] * (reader.MAX_MEMBERS + 1)):
            with self.subTest(retain=type(retain).__name__):
                with self.assertRaises(reader.ArchiveError):
                    reader.read_archive(self.path, retain=retain)

    def test_rejects_unsafe_member_names(self):
        for name in ("../escape", "/absolute", "C:/drive", "a\\b", "a//b", "a/./b",
                     "a/../b", "a/", ".", "..", "a\nb", "a\tb", "\u00e9.json",
                     "a/" * 17 + "b", "a" * 256):
            with self.subTest(name=repr(name)):
                self.write([(name, b"inert")])
                self.reject()

    def test_rejects_nul_hidden_in_original_name(self):
        original = self.write([("run/x.json", b"{}")])
        self.reject(original.replace(b"run/x.json", b"run/\0.json"))

    def test_rejects_duplicate_case_alias_and_parent_file(self):
        for names in (("same", "same"), ("Same", "same"), ("run", "run/summary.json"),
                      ("RUN", "run/summary.json")):
            with self.subTest(names=names):
                self.write([(name, b"x") for name in names])
                self.reject()

    def test_rejects_links_and_nonregular_attributes(self):
        for kind in (stat.S_IFLNK, stat.S_IFDIR, stat.S_IFIFO, stat.S_IFSOCK,
                     stat.S_IFCHR, stat.S_IFBLK):
            for creator in (0, 3):
                with self.subTest(kind=kind, creator=creator):
                    self.write(attributes=(kind | 0o644) << 16, creator=creator)
                    self.reject()
        for attributes in (0x10, 0x8, 0x400, (stat.S_IFREG | 0o4755) << 16):
            with self.subTest(attributes=attributes):
                self.write(attributes=attributes)
                self.reject()

    def test_rejects_encrypted_or_reserved_flags(self):
        original = self.write()
        central = self.central(original)
        for flag in (1, 0x40, 0x2000, 0x8000):
            with self.subTest(flag=flag):
                body = bytearray(original)
                struct.pack_into("<H", body, 6, flag)
                struct.pack_into("<H", body, central + 8, flag)
                self.reject(body)

    def test_rejects_unsupported_compression(self):
        original = self.write()
        for method in (12, 14, 99):
            with self.subTest(method=method):
                body = bytearray(original)
                struct.pack_into("<H", body, 8, method)
                struct.pack_into("<H", body, self.central(body) + 10, method)
                self.reject(body)

    def test_rejects_bad_crc_even_for_unretained_members(self):
        original = bytearray(self.write([("logs/governance.log", b"abcdef")], method=0))
        name_size = struct.unpack_from("<H", original, 26)[0]
        original[30 + name_size] ^= 1
        self.path.write_bytes(original)
        with self.assertRaisesRegex(reader.ArchiveError, "CRC"):
            reader.read_archive(self.path, retain=())

    def test_rejects_outer_truncation_and_trailing_bytes(self):
        original = self.write()
        for body in (original[:-1], original[:30], original + b"trailer", b"", b"not zip" * 10):
            with self.subTest(size=len(body)):
                self.reject(body)

    def test_rejects_incomplete_deflate_with_intact_zip_records(self):
        plain = b"complete body" * 100
        self.raw_zip(plain=plain, compressed=self.deflate(plain)[:-1])
        with self.assertRaisesRegex(reader.ArchiveError, "incomplete"):
            reader.read_archive(self.path)

    def test_rejects_deflate_trailing_bytes_and_concatenated_streams(self):
        plain = b"complete body" * 100
        for suffix in (b"junk", self.deflate(b"second")):
            with self.subTest(suffix_length=len(suffix)):
                self.raw_zip(plain=plain, compressed=self.deflate(plain) + suffix)
                self.reject()

    def test_rejects_forged_expanded_size(self):
        plain = b"size must not hide output" * 100
        for size in (0, len(plain) - 1, len(plain) + 1):
            with self.subTest(size=size):
                self.raw_zip(plain=plain, compressed=self.deflate(plain), size=size)
                self.reject()
        self.raw_zip(plain=b"stored", compressed=b"stored", size=0, method=0)
        self.reject()

    def test_chunk_bound_handles_high_expansion(self):
        plain = b"x" * 200000
        self.write([("run/events.jsonl", plain)])
        with mock.patch.object(reader, "CHUNK_BYTES", 257):
            self.assertEqual(reader.read_archive(self.path)["members"]["run/events.jsonl"], plain)

    def test_rejects_size_limits_before_member_expansion(self):
        original = self.write([("one", b"1" * 5), ("two", b"2" * 5)])
        for constant, maximum in (("MAX_ARCHIVE_BYTES", len(original) - 1),
                                  ("MAX_MEMBER_BYTES", 4), ("MAX_TOTAL_BYTES", 9),
                                  ("MAX_MEMBERS", 1), ("MAX_DIRECTORY_BYTES", 1)):
            with self.subTest(constant=constant), mock.patch.object(reader, constant, maximum):
                self.reject()

    def test_directory_bound_is_enforced_before_zipfile_allocates_entries(self):
        self.write()
        with mock.patch.object(reader, "MAX_DIRECTORY_BYTES", 1), \
             mock.patch.object(zipfile, "ZipFile", side_effect=AssertionError("unbounded parse")):
            self.reject()

    def test_rejects_local_name_crc_size_and_flag_disagreement(self):
        original = self.write()
        for offset, code, value in ((30, "B", ord("x")), (14, "I", 0),
                                    (18, "I", 0), (22, "I", 0), (6, "H", 8)):
            with self.subTest(offset=offset):
                self.mutate(original, offset, code, value)

    def test_rejects_bad_data_descriptor(self):
        original = self.write(descriptor=True)
        descriptor = original.index(b"PK\x07\x08")
        for offset in (descriptor, descriptor + 4, descriptor + 8, descriptor + 12):
            with self.subTest(offset=offset):
                self.mutate(original, offset, "I", 0)

    def test_accepts_unsigned_data_descriptor(self):
        original = self.write(descriptor=True)
        descriptor = original.index(b"PK\x07\x08")
        body = bytearray(original[:descriptor] + original[descriptor + 4:])
        struct.pack_into("<I", body, len(body) - 6, self.central(original) - 4)
        self.path.write_bytes(body)
        self.assertEqual(reader.read_archive(self.path)["member_count"], 1)

    def test_rejects_overlapping_offsets_and_gaps(self):
        original = self.write([("one", b"1"), ("two", b"2")])
        second_central = original.index(b"PK\x01\x02", self.central(original) + 4)
        self.mutate(original, second_central + 42, "I", 0)
        self.raw_zip(plain=b"x", compressed=b"x", method=0, gap=b"hidden")
        self.reject()

    def test_rejects_directory_count_disk_and_zip64_sentinels(self):
        original = self.write()
        end = len(original) - 22
        for offset, code, value in ((end + 4, "H", 1), (end + 6, "H", 1),
                                    (end + 8, "H", 2), (end + 10, "H", 65535),
                                    (end + 12, "I", 0xFFFFFFFF), (end + 16, "I", 0xFFFFFFFF)):
            with self.subTest(offset=offset):
                self.mutate(original, offset, code, value)

    def test_rejects_empty_archives_and_comments(self):
        self.write([])
        self.reject()
        self.write()
        with zipfile.ZipFile(self.path, "a") as archive:
            archive.comment = b"unsupported comment"
        self.reject()

    def test_rejects_member_extras_and_comments(self):
        for field, value in (("extra", b"\x55\x54\x01\x00\x00"), ("comment", b"comment")):
            with self.subTest(field=field):
                with zipfile.ZipFile(self.path, "w") as archive:
                    info = zipfile.ZipInfo("run/summary.json")
                    setattr(info, field, value)
                    archive.writestr(info, b"{}")
                self.reject()

    def test_rejects_unsafe_local_path_text(self):
        self.write()
        for path in ("relative.zip", str(self.base) + "/./governance.zip",
                     str(self.base) + "//governance.zip", str(self.base) + "/../governance.zip",
                     "/", str(self.path) + "\n", bytes(self.path), None):
            with self.subTest(path_type=type(path).__name__):
                with self.assertRaises(reader.ArchiveError):
                    reader.read_archive(path)

    def test_rejects_missing_directory_fifo_and_hardlinked_input(self):
        with self.assertRaises(reader.ArchiveError):
            reader.read_archive(self.path)
        self.path.mkdir()
        self.reject()
        self.path.rmdir()
        os.mkfifo(self.path)
        self.reject()
        self.path.unlink()
        self.write()
        os.link(self.path, self.base / "other.zip")
        self.reject()

    def test_rejects_leaf_and_ancestor_symlinks(self):
        self.write()
        leaf = self.base / "link.zip"
        leaf.symlink_to(self.path)
        ancestor = self.base / "linked"
        ancestor.symlink_to(self.base, target_is_directory=True)
        for path in (leaf, ancestor / self.path.name):
            with self.subTest(path=path.name):
                with self.assertRaises(reader.ArchiveError):
                    reader.read_archive(path)

    def test_rejects_file_replacement_during_inspection(self):
        original = self.write()
        member_bytes = reader._member_bytes

        def replace(*arguments):
            result = member_bytes(*arguments)
            replacement = self.base / "replacement.zip"
            replacement.write_bytes(original)
            replacement.replace(self.path)
            return result

        with mock.patch.object(reader, "_member_bytes", side_effect=replace):
            with self.assertRaisesRegex(reader.ArchiveError, "changed"):
                reader.read_archive(self.path)

    def test_rejects_in_place_mutation_during_inspection(self):
        original = self.write()
        member_bytes = reader._member_bytes

        def change(*arguments):
            result = member_bytes(*arguments)
            changed = bytearray(original)
            changed[-1] ^= 1
            self.path.write_bytes(changed)
            return result

        with mock.patch.object(reader, "_member_bytes", side_effect=change):
            with self.assertRaisesRegex(reader.ArchiveError, "changed"):
                reader.read_archive(self.path)


if __name__ == "__main__":
    unittest.main()
