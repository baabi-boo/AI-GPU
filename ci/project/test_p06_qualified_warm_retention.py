#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Synthetic producer-format and adversarial offline retention checks."""

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import p06_qualified_warm_encrypt as producer
import p06_qualified_warm_retention as retention


REVISION = "0123456789abcdef0123456789abcdef01234567"


def fixture(files=None, directories=(), *, manifest=None, manifest_bytes=None, edit_header=None):
    """Use the unchanged producer's actual metadata and member-order functions."""
    files = {"payload": b"opaque\x00\xffPRIVATE"} if files is None else files
    directory_names = {"", *directories}
    for name in [*files, *directories]:
        parts = name.split("/")
        directory_names.update("/".join(parts[:index]) for index in range(1, len(parts)))
    if manifest is None:
        manifest = {"schema_version": 1, "contract_id": producer.CONTRACT_ID,
                    "expected_revision": REVISION, "directories": sorted(directory_names),
                    "files": [{"path": name, "size_bytes": len(body),
                               "sha256": hashlib.sha256(body).hexdigest()}
                              for name, body in sorted(files.items())]}
    raw = producer._json_bytes(manifest) if manifest_bytes is None else manifest_bytes
    entries = {name: SimpleNamespace(size=0, directory=True) for name in directory_names}
    entries.update({name: SimpleNamespace(size=len(body), directory=False) for name, body in files.items()})
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT,
                      encoding="utf-8", errors="strict") as archive:
        for info, entry in producer._tar_members(entries, raw):
            if edit_header is not None:
                edit_header(info)
            body = raw if entry is None else files.get(info.name.removeprefix("private/"), b"")
            archive.addfile(info, io.BytesIO(body) if info.isfile() else None)
    return output.getvalue(), manifest, raw


def change_header(data, offset, start, end, replacement):
    body = bytearray(data)
    body[offset + start:offset + end] = replacement
    body[offset + 148:offset + 156] = b" " * 8
    checksum = sum(body[offset:offset + 512])
    body[offset + 148:offset + 156] = f"{checksum:06o}\0 ".encode("ascii")
    return bytes(body)


class RetentionReaderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.archive = self.root / "retained.tar"

    def save(self, data):
        self.archive.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def inspect(self, data, **kwargs):
        return retention.inspect_archive(self.archive, self.save(data),
                                         expected_revision=REVISION, **kwargs)

    def rejects(self, data, code, **kwargs):
        with self.assertRaisesRegex(retention.RetentionError, "^" + code + "$"):
            self.inspect(data, **kwargs)

    def test_producer_tree_roundtrip_preserves_hidden_empty_and_opaque_payloads(self):
        files = {".hidden/log": b"\x00\xffPRIVATE", "manifest.json": b"retained manifest payload",
                 "empty": b"", "retained.py": b"raise RuntimeError('must remain inert')\n"}
        data, manifest, raw = fixture(files, [".empty", "plain-empty"])
        digest = self.save(data)
        with mock.patch.object(tarfile.TarFile, "extract", side_effect=AssertionError), \
             mock.patch.object(tarfile.TarFile, "extractall", side_effect=AssertionError), \
             mock.patch("subprocess.run", side_effect=AssertionError), \
             retention.RetentionArchive(self.archive, digest, expected_revision=REVISION) as archive:
            self.assertEqual(archive.manifest, manifest)
            self.assertEqual(archive.manifest_bytes, raw)
            self.assertEqual(set(archive.entries), set(files) | {"", ".hidden", ".empty", "plain-empty"})
            for index, (name, body) in enumerate(files.items()):
                with (self.root / f"copy-{index}").open("xb") as output:
                    archive.copy_file(name, output.fileno())
                self.assertEqual((self.root / f"copy-{index}").read_bytes(), body)
            report = archive.report()
            self.assertTrue(report["retention_verified"])
            self.assertEqual(report["archive_sha256"], digest)
            self.assertEqual(report["input_bytes"], sum(map(len, files.values())))
            for field in ("retained_code_executed", "origin_authenticated", "native_acceptance",
                          "performance_acceptance", "phase_acceptance"):
                self.assertIs(report[field], False)
            self.assertEqual(report["native_execution"], "not_run")

    def test_path_only_pax_accepts_unicode_exact_name_boundaries_and_maximum_relative_paths(self):
        longest_parent = "/".join(["a" * 31] * 127)
        files = {"é": b"unicode", "😀": b"pair", "é" * 127 + "x": b"component-limit",
                 "x" * 92: b"100-byte-header", "y" * 93: b"pax-header",
                 " leading = trailing ": b"spaces", "\u0080": b"allowed-producer-character",
                 longest_parent + "/" + "f" * 32: b"4096-byte-128-component-file"}
        directories = ["d" * 91, "e" * 92, longest_parent + "/" + "g" * 32]
        data, _, _ = fixture(files, directories)
        report = self.inspect(data)
        self.assertEqual(report["file_count"], len(files))
        self.assertIn(b"19 path=private/\xc3\xa9\n", data)
        self.assertIn(b"private/?", data)
        self.assertEqual(len((longest_parent + "/" + "f" * 32).encode()), 4096)

    def test_empty_input_tree_has_root_and_manifest(self):
        data, _, _ = fixture({})
        report = self.inspect(data)
        self.assertEqual((report["file_count"], report["directory_count"], report["input_bytes"]), (0, 1, 0))
        self.assertEqual(report["archive_bytes"], tarfile.RECORDSIZE)

    def test_manifest_schema_types_order_and_json_encoding_are_exact(self):
        _, original, _ = fixture()
        cases = [
            (lambda m: m.update(extra="PRIVATE"), "manifest-schema"),
            (lambda m: m.update(schema_version=True), "manifest-schema"),
            (lambda m: m.update(directories={"": True}), "manifest-schema"),
            (lambda m: m["files"][0].update(extra=0), "manifest-schema"),
            (lambda m: m["files"][0].update(size_bytes=True), "file-limit"),
            (lambda m: m["files"][0].update(sha256="A" * 64), "manifest-schema"),
            (lambda m: m.update(directories=["", "z", "a"]), "manifest-schema"),
            (lambda m: m.update(files=[m["files"][0], dict(m["files"][0], path="a")]), "manifest-schema"),
        ]
        for edit, code in cases:
            manifest = copy.deepcopy(original)
            edit(manifest)
            with self.subTest(manifest=manifest):
                self.rejects(fixture(manifest=manifest)[0], code)
        raw = producer._json_bytes(original)
        for malformed in (raw.replace(b'{"contract_id":', b'{"schema_version":1,"contract_id":', 1),
                          raw.rstrip(b"\n"), json.dumps(original, indent=2).encode(),
                          raw.replace(b'"size_bytes":15', b'"size_bytes":NaN'), b"\xff"):
            with self.subTest(raw=malformed[:40]):
                self.rejects(fixture(manifest_bytes=malformed)[0], "manifest-format")
        self.rejects(fixture(manifest_bytes=b"[" * 10000 + b"]" * 10000)[0],
                     "manifest-(format|schema)")

    def test_exact_revision_binding_rejects_null_and_other_revision(self):
        _, original, _ = fixture()
        for revision in (None, "f" * 40):
            with self.subTest(revision=revision):
                self.rejects(fixture(manifest=dict(original, expected_revision=revision))[0], "revision-mismatch")
        data, _, _ = fixture()
        digest = self.save(data)
        for expected in (None, "HEAD", "F" * 40, True):
            with self.subTest(expected=expected), self.assertRaisesRegex(retention.RetentionError, "invalid-argument"):
                retention.RetentionArchive(self.archive, digest, expected_revision=expected)

    def test_manifest_namespace_requires_canonical_names_and_declared_parents(self):
        _, original, _ = fixture()
        for name in ("/absolute", "../escape", "x//y", "x/./y", "bad\\name", "bad:name",
                     "bad\nname", "bad\x7fname", "e\u0301", "\ud800", "x" * 256,
                     "/".join(["x"] * 129)):
            manifest = copy.deepcopy(original)
            manifest["files"][0]["path"] = name
            with self.subTest(name=name):
                self.rejects(fixture(manifest=manifest)[0], "noncanonical-path")
        for directories, name, code in (([], "payload", "manifest-schema"),
                                         (["", ""], "payload", "path-alias"),
                                         (["", "payload"], "payload", "path-alias"),
                                         (["", "PAYLOAD"], "payload", "path-alias"),
                                         ([""], "missing/payload", "parent-missing")):
            manifest = copy.deepcopy(original)
            manifest["directories"] = directories
            manifest["files"][0]["path"] = name
            with self.subTest(directories=directories, name=name):
                self.rejects(fixture(manifest=manifest)[0], code)

    def test_resource_bounds_reject_before_payload_copy(self):
        data, _, _ = fixture()
        for bound, maximum, code in (("MAX_ENTRIES", 1, "entry-limit"),
                                     ("MAX_FILE_BYTES", 1, "file-limit"),
                                     ("MAX_INPUT_BYTES", 1, "input-byte-limit"),
                                     ("MAX_MANIFEST_BYTES", 1, "manifest-byte-limit"),
                                     ("MAX_ARCHIVE_BYTES", 1, "archive-byte-limit")):
            with self.subTest(bound=bound), mock.patch.object(retention, bound, maximum):
                self.rejects(data, code)

    def test_raw_member_headers_cannot_introduce_links_specials_or_alternate_metadata(self):
        data, _, raw = fixture()
        root_offset = 512 + ((len(raw) + 511) // 512) * 512
        file_offset = root_offset + 512
        for typeflag in (b"1", b"2", b"3", b"4", b"6", b"7", b"S", b"x", b"g", b"L", b"K", b"\0"):
            with self.subTest(typeflag=typeflag):
                self.rejects(change_header(data, file_offset, 156, 157, typeflag), "archive-format")
        for offset, start, end, replacement in (
                (root_offset, 0, 8, b"private\0"),
                (file_offset, 100, 108, b"0000644\0"),
                (file_offset, 108, 116, b"0000001\0"),
                (file_offset, 124, 136, b"\x80" + bytes(11)),
                (file_offset, 345, 350, b"extra")):
            with self.subTest(field=start):
                self.rejects(change_header(data, offset, start, end, replacement), "archive-format")

    def test_pax_state_overrides_and_fallback_aliases_are_rejected(self):
        data, _, _ = fixture({"é": b"x"})
        offset = next(index for index in range(0, len(data), 512)
                      if data[index:index + 15] == b"././@PaxHeader\0")
        for start, end, replacement in ((156, 157, b"g"), (124, 136, b"77777777777\0")):
            with self.subTest(field=start):
                self.rejects(change_header(data, offset, start, end, replacement), "archive-format")
        fallback = offset + 1024
        self.rejects(change_header(data, fallback, 0, 9, b"private/x"), "archive-format")
        for pax_headers in ({"size": "1"}, {"linkpath": "outside"}, {"GNU.sparse.map": "0,1"}):
            def edit(info):
                if info.name == "private/é":
                    info.pax_headers.update(pax_headers)
            with self.subTest(pax_headers=pax_headers):
                self.rejects(fixture({"é": b"x"}, edit_header=edit)[0], "archive-format")

    def test_file_hash_is_checked_even_when_caller_supplies_modified_archive_hash(self):
        data, _, _ = fixture()
        changed = data.replace(b"opaque\x00\xffPRIVATE", b"broken\x00\xffPRIVATE", 1)
        self.rejects(changed, "file-sha256")
        self.save(data)
        with self.assertRaisesRegex(retention.RetentionError, "archive-sha256"):
            retention.inspect_archive(self.archive, "0" * 64, expected_revision=REVISION)

    def test_eof_and_all_member_padding_are_exact_bytes(self):
        data, _, raw = fixture()
        bad_manifest_padding = bytearray(data)
        bad_manifest_padding[512 + len(raw)] = 1
        bad_payload_padding = bytearray(data)
        payload = data.index(b"opaque\x00\xffPRIVATE")
        bad_payload_padding[payload + 15] = 1
        bad_trailer = bytearray(data)
        bad_trailer[-1] = 1
        for changed in (data[:-1], data[:512], data + bytes(10240), data + data,
                        bytes(bad_manifest_padding), bytes(bad_payload_padding), bytes(bad_trailer)):
            with self.subTest(size=len(changed)), self.assertRaises(retention.RetentionError):
                self.inspect(changed)

    def test_physical_inventory_cannot_duplicate_omit_reorder_or_add_members(self):
        data, _, raw = fixture({"a": b"A", "b": b"B"})
        first = 512 + ((len(raw) + 511) // 512) * 512 + 512
        second = first + 1024
        duplicate = change_header(data, second, 0, 9, b"private/a")
        omitted = data[:second] + data[second + 1024:] + bytes(1024)
        reordered = data[:first] + data[second:second + 1024] + data[first:second] + data[second + 1024:]
        added = data[:second + 1024] + data[first:first + 512] + data[second + 1536:]
        for changed in (duplicate, omitted, reordered, added):
            with self.subTest(prefix=changed[first:first + 9]):
                self.rejects(changed, "archive-format")

    def test_source_links_special_files_and_noncanonical_paths_fail_without_sensitive_errors(self):
        data, _, _ = fixture()
        digest = self.save(data)
        symlink = self.root / "PRIVATE-symlink"
        symlink.symlink_to(self.archive)
        hardlink = self.root / "PRIVATE-hardlink"
        os.link(self.archive, hardlink)
        fifo = self.root / "PRIVATE-fifo"
        os.mkfifo(fifo)
        for path in (symlink, hardlink, fifo, self.root / "PRIVATE-missing", self.root):
            with self.subTest(path=path), self.assertRaises(retention.RetentionError) as caught:
                retention.inspect_archive(path, digest, expected_revision=REVISION)
            self.assertNotIn("PRIVATE", str(caught.exception))
            self.assertIn(caught.exception.code, retention.ERROR_CODES)
        hardlink.unlink()
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(retention.RetentionError):
            retention.inspect_archive(alias / self.archive.name, digest, expected_revision=REVISION)
        for path in ("relative.tar", str(self.root) + "/./retained.tar", str(self.root) + "//retained.tar"):
            with self.subTest(path=path), self.assertRaisesRegex(retention.RetentionError, "noncanonical-path"):
                retention.RetentionArchive(path, digest, expected_revision=REVISION)

    def test_observed_archive_mutation_or_replacement_cannot_leave_success_context(self):
        data, _, _ = fixture()
        for replacement in (False, True):
            digest = self.save(data)
            with self.subTest(replacement=replacement), self.assertRaisesRegex(retention.RetentionError, "archive-changed"):
                with retention.RetentionArchive(self.archive, digest, expected_revision=REVISION):
                    if replacement:
                        self.archive.unlink()
                    self.archive.write_bytes(data.replace(b"opaque", b"broken", 1))

    def test_copy_uses_private_validated_metadata_and_rehashes_each_source(self):
        data, _, _ = fixture()
        digest = self.save(data)
        with retention.RetentionArchive(self.archive, digest, expected_revision=REVISION) as archive:
            archive.manifest["expected_revision"] = "f" * 40
            archive.entries["payload"]["size_bytes"] = 1
            self.assertEqual(archive.report()["expected_revision"], REVISION)
            for name in ("", "missing"):
                with self.assertRaisesRegex(retention.RetentionError, "unknown-file"):
                    archive.copy_file(name, 0)
            output = self.root / "output"
            output.write_bytes(b"unrelated")
            with output.open("r+b") as stream, self.assertRaisesRegex(retention.RetentionError, "copy-output"):
                archive.copy_file("payload", stream.fileno())
            offset = archive.entries["payload"]["offset"]
            original = os.pread
            def changed_read(fd, length, position):
                body = original(fd, length, position)
                return b"X" * len(body) if position == offset else body
            with (self.root / "new").open("xb") as stream, \
                 mock.patch.object(retention.os, "pread", side_effect=changed_read), \
                 self.assertRaisesRegex(retention.RetentionError, "file-sha256"):
                archive.copy_file("payload", stream.fileno())
        with self.assertRaisesRegex(retention.RetentionError, "reader-state"):
            archive.report()

    def test_copy_streams_bounded_reads_and_retries_short_writes(self):
        payload = bytes(range(256)) * 513
        data, _, _ = fixture({"large": payload})
        digest = self.save(data)
        original_read, original_write = os.pread, os.write
        requested = []
        def bounded_read(fd, length, position):
            requested.append(length)
            self.assertLessEqual(length, retention.CHUNK_BYTES)
            return original_read(fd, length, position)
        def short_write(fd, body):
            return original_write(fd, body[:4096])
        with mock.patch.object(retention.os, "pread", side_effect=bounded_read), \
             retention.RetentionArchive(self.archive, digest, expected_revision=REVISION) as archive:
            with (self.root / "large-copy").open("xb") as output, \
                 mock.patch.object(retention.os, "write", side_effect=short_write):
                archive.copy_file("large", output.fileno())
            with (self.root / "failed-copy").open("xb") as output, \
                 mock.patch.object(retention.os, "write", return_value=0), \
                 self.assertRaisesRegex(retention.RetentionError, "copy-failed"):
                archive.copy_file("large", output.fileno())
        self.assertIn(retention.CHUNK_BYTES, requested)
        self.assertEqual((self.root / "large-copy").read_bytes(), payload)

    def test_mutating_public_metadata_cannot_change_successful_copies_or_report(self):
        files = {"alpha": b"original-A\x00\xff", "dir/bravo": b"other-distinct-payload"}
        data, manifest, raw = fixture(files)
        digest = self.save(data)
        with retention.RetentionArchive(self.archive, digest, expected_revision=REVISION) as archive:
            report = archive.report()
            entries = copy.deepcopy(archive.entries)
            exposed_manifest = archive.manifest
            exposed_manifest["expected_revision"] = "f" * 40
            exposed_manifest["directories"].clear()
            exposed_manifest["files"][0].update(path="changed", size_bytes=0, sha256="0" * 64)
            exposed_manifest["files"].append({"path": "phantom", "size_bytes": 1, "sha256": "f" * 64})
            exposed_entries = archive.entries
            exposed_entries["alpha"].update(directory=True,
                                             size_bytes=entries["dir/bravo"]["size_bytes"],
                                             sha256=entries["dir/bravo"]["sha256"],
                                             offset=entries["dir/bravo"]["offset"])
            del exposed_entries["dir/bravo"]
            exposed_entries["phantom"] = dict(exposed_entries["alpha"])
            self.assertEqual(archive.manifest, manifest)
            self.assertEqual(archive.manifest_bytes, raw)
            self.assertEqual(archive.entries, entries)
            self.assertEqual(archive.report(), report)
            for index, (name, body) in enumerate(files.items()):
                output = self.root / f"isolated-copy-{index}"
                with output.open("xb") as stream:
                    archive.copy_file(name, stream.fileno())
                self.assertEqual(output.read_bytes(), body)
            self.assertEqual(archive.report(), report)

    def test_final_archive_hash_is_checked_independently_of_identity_observations(self):
        data, _, _ = fixture()
        digest = self.save(data)
        with self.assertRaisesRegex(retention.RetentionError, "archive-changed"):
            with retention.RetentionArchive(self.archive, digest, expected_revision=REVISION) as archive:
                with mock.patch.object(archive._archive, "assert_identity"):
                    self.archive.write_bytes(data.replace(b"opaque", b"broken", 1))
                    archive.assert_unchanged()

    def test_summary_is_bounded_consistency_only_and_never_plaintext_hash_identity(self):
        data, manifest, _ = fixture()
        summary = {"schema_version": 1, "contract_id": producer.CONTRACT_ID,
                   "expected_revision": REVISION, "outcome": "pass", "encryption_passed": True,
                   "file_count": len(manifest["files"]), "directory_count": len(manifest["directories"]),
                   "input_bytes": 15, "ciphertext_bytes": len(data) + 200, "ciphertext_sha256": "f" * 64}
        path = self.root / "summary.json"
        path.write_bytes(producer._json_bytes(summary))
        checked = self.inspect(data, summary=path)
        self.assertTrue(checked["summary_checked"])
        self.assertIn("public-summary-ciphertext-is-not-verified", checked["limitations"])
        for key, value, code in (("file_count", 2, "summary-mismatch"),
                                 ("expected_revision", "e" * 40, "summary-mismatch"),
                                 ("file_count", True, "summary-format"),
                                 ("encryption_passed", 1, "summary-format"),
                                 ("ciphertext_sha256", "G" * 64, "summary-format")):
            path.write_bytes(producer._json_bytes(dict(summary, **{key: value})))
            with self.subTest(key=key):
                self.rejects(data, code, summary=path)
        path.write_bytes(producer._json_bytes(summary))
        digest = self.save(data)
        with self.assertRaisesRegex(retention.RetentionError, "summary-changed"):
            with retention.RetentionArchive(self.archive, digest, expected_revision=REVISION, summary=path):
                path.write_bytes(producer._json_bytes(dict(summary, ciphertext_sha256="e" * 64)))


if __name__ == "__main__":
    unittest.main()
