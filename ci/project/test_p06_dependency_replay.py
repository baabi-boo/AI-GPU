# SPDX-License-Identifier: Apache-2.0
"""ZIP transport controls; synthetic wrapper fixtures do not model a fresh build."""

import contextlib
import copy
import encodings.cp437
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import marshal
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

import p06_dependency_contract as contract
import p06_dependency_receipt as receipt
import p06_dependency_replay as replay


REVISION = "a" * 40
PREFIX = replay.DEFAULT_PREFIX


def sha256(body):
    return hashlib.sha256(body).hexdigest()


def descriptor(path, body):
    return {"path": path, "sha256": sha256(body), "size_bytes": len(body)}


class DependencyArchiveTransportTests(unittest.TestCase):
    """Use real ZIP bytes while explicitly replacing only full build semantics."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p06-dependency-replay-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "original.zip"
        self.payloads = {
            "sources/yaml-cpp/docs/How-To-Parse-A-Document-(Old-API).md": b"immutable source document\n",
            "helpers/inert.py": b"raise AssertionError('retained code was executed')\n",
            "commands.json": b'{"argv":["/never-open-producer/tool","$(touch /never-create)"]}\n',
            "payloads/library.bin": b"\x7fELF\x00inert retained binary",
        }
        self.document = {"expected_revision": REVISION, "contract_id": contract.CONTRACT_ID,
            "retained_files": [descriptor(name, body) for name, body in sorted(self.payloads.items())]}

    def make_zip(self, *, document=None, payloads=None, extra=(), raw_report=None, prefix=PREFIX):
        document = self.document if document is None else document
        payloads = self.payloads if payloads is None else payloads
        body = contract.json_bytes(document) + b"\n" if raw_report is None else raw_report
        select = lambda name: prefix + "/" + name if prefix else name
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.path, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr(select("report.json"), body)
                for name, payload in payloads.items():
                    archive.writestr(select(name), payload)
                for name, payload in extra:
                    archive.writestr(name, payload)
        self.receipt_sha256 = sha256(body)
        self.zip_sha256 = sha256(self.path.read_bytes())
        return self.path

    def synthetic_semantics(self, document, read, *, expected_revision):
        # This replacement isolates wrapper boundaries. The actual full reader
        # is exercised by its dedicated tests and the eventual hosted original.
        receipt.require(document["expected_revision"] == expected_revision,
                        "synthetic source revision differs")
        receipt.require(document["contract_id"] == contract.CONTRACT_ID,
                        "synthetic dependency contract differs")
        for row in document["retained_files"]:
            first = receipt.descriptor(row, read)
            self.assertIs(read(row["path"]), first)
            self.assertEqual(read(row["path"]), self.payloads[row["path"]])
        return {"synthetic_wrapper_control": True,
                "source_revision": expected_revision, **dict.fromkeys(contract.FALSE_CLAIMS, False)}

    def check(self, **options):
        arguments = {"expected_revision": REVISION,
                     "expected_receipt_sha256": self.receipt_sha256}
        arguments.update(options)
        return replay.replay_archive(self.path, self.zip_sha256, **arguments)

    def test_external_pins_full_inventory_and_cache_are_bound(self):
        self.make_zip(extra=[("other-hosted-packet/report.json", b"unreviewed separate scope")])
        with mock.patch.object(receipt, "verify_document", side_effect=self.synthetic_semantics) as semantic:
            result = self.check()
        semantic.assert_called_once()
        self.assertEqual(result["outcome"], "pass")
        self.assertIs(result["retained_consistency"], True)
        self.assertEqual(result["source_revision"], REVISION)
        self.assertEqual(result["dependency_receipt_sha256"], self.receipt_sha256)
        self.assertEqual(result["dependency_report"]["sha256"], self.receipt_sha256)
        self.assertEqual(result["packet_files_checked"], len(self.payloads) + 1)
        self.assertEqual(result["archive_read"]["read_count"], len(self.payloads) + 1)
        self.assertEqual(result["archive_read"]["read_attempts"], len(self.payloads) + 1)
        self.assertEqual(result["archive_read"]["read_bytes"], result["packet_bytes_checked"])
        self.assertEqual(result["archive_read"]["data_files"], len(self.payloads) + 2)
        self.assertEqual(result["native_execution"], "not_run")
        self.assertIs(result["retained_code_executed"], False)
        self.assertEqual(result["trusted_reader_sources"], replay.TRUSTED_READER_SOURCES)
        self.assertTrue(result["retained_dependency_verification"]["synthetic_wrapper_control"])
        for name in contract.FALSE_CLAIMS:
            self.assertIs(result[name], False)

    def test_retained_code_commands_binaries_and_producer_paths_remain_inert(self):
        self.make_zip()
        original_open = Path.open

        def guarded_open(path, *args, **kwargs):
            if str(path).startswith("/never-open-producer"):
                raise AssertionError("recorded producer path was opened")
            return original_open(path, *args, **kwargs)

        with mock.patch.object(receipt, "verify_document", side_effect=self.synthetic_semantics), \
             mock.patch("subprocess.Popen", side_effect=AssertionError("retained process started")), \
             mock.patch("os.system", side_effect=AssertionError("retained shell command executed")), \
             mock.patch("runpy.run_path", side_effect=AssertionError("retained Python executed")), \
             mock.patch.object(zipfile.ZipFile, "extract", side_effect=AssertionError("archive extracted")), \
             mock.patch.object(zipfile.ZipFile, "extractall", side_effect=AssertionError("archive extracted")), \
             mock.patch.object(Path, "open", new=guarded_open):
            result = self.check()
        self.assertFalse(result["retained_code_executed"])

    def test_synthetic_transport_packet_cannot_pass_real_dependency_semantics(self):
        self.make_zip()
        with self.assertRaisesRegex(ValueError, "dependency build report fields differ"):
            self.check()

    def test_wrong_archive_and_receipt_pins_reject_before_semantic_review(self):
        self.make_zip()
        with mock.patch.object(receipt, "verify_document") as semantic:
            with self.assertRaisesRegex(ValueError, "original ZIP SHA-256 differs"):
                replay.replay_archive(self.path, "0" * 64, expected_revision=REVISION,
                    expected_receipt_sha256=self.receipt_sha256)
            with self.assertRaisesRegex(ValueError, "dependency receipt SHA-256 differs"):
                self.check(expected_receipt_sha256="0" * 64)
        semantic.assert_not_called()

    def test_external_pin_types_and_revision_are_required(self):
        self.make_zip()
        for changes in ({"expected_revision": "master"}, {"expected_revision": "A" * 40},
                        {"expected_revision": True}, {"expected_receipt_sha256": "abc"},
                        {"expected_receipt_sha256": None}, {"prefix": False}):
            with self.subTest(changes=changes), mock.patch.object(replay, "_archive_api") as api, \
                 self.assertRaises(ValueError):
                self.check(**changes)
            api.assert_not_called()

    def test_selected_revision_is_delivered_to_semantic_reader(self):
        self.make_zip()
        with mock.patch.object(receipt, "verify_document", side_effect=self.synthetic_semantics), \
             self.assertRaisesRegex(ValueError, "synthetic source revision differs"):
            self.check(expected_revision="b" * 40)

    def test_prefix_is_literal_and_must_select_the_exact_packet(self):
        self.make_zip()
        for prefix in ("../dependency-build", "/dependency-build", "a//b", "a/./b", "a\\b", "C:/a"):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                self.check(prefix=prefix)
        with self.assertRaisesRegex(ValueError, "prefix has no retained files"):
            self.check(prefix="missing")

    def test_empty_prefix_can_select_a_dependency_only_archive(self):
        self.make_zip(prefix="")
        with mock.patch.object(receipt, "verify_document", side_effect=self.synthetic_semantics):
            result = self.check(prefix="")
        self.assertEqual(result["prefix"], "")

    def test_unlisted_missing_duplicate_and_self_listed_members_reject(self):
        scenarios = []
        extra = dict(self.payloads, **{"unlisted.txt": b"extra"})
        scenarios.append((self.document, extra))
        missing = dict(self.payloads)
        missing.pop("helpers/inert.py")
        scenarios.append((self.document, missing))
        duplicate = copy.deepcopy(self.document)
        duplicate["retained_files"].append(duplicate["retained_files"][0])
        scenarios.append((duplicate, self.payloads))
        self_listed = copy.deepcopy(self.document)
        self_listed["retained_files"].append(descriptor("report.json", b"not a real self hash"))
        scenarios.append((self_listed, self.payloads))
        for index, (document, payloads) in enumerate(scenarios):
            with self.subTest(index=index), mock.patch.object(receipt, "verify_document") as semantic:
                self.make_zip(document=document, payloads=payloads)
                with self.assertRaises(ValueError):
                    self.check()
                semantic.assert_not_called()

    def test_wrong_retained_size_digest_and_descriptor_fields_reject(self):
        for field, value in (("sha256", "0" * 64), ("size_bytes", 0),
                             ("size_bytes", True), ("size_bytes", contract.MAX_FILE_BYTES + 1),
                             ("path", "../producer"), ("unknown", "extra")):
            document = copy.deepcopy(self.document)
            document["retained_files"][0][field] = value
            with self.subTest(field=field, value=value), mock.patch.object(receipt, "verify_document") as semantic:
                self.make_zip(document=document)
                with self.assertRaises(ValueError):
                    self.check()
                semantic.assert_not_called()

    def test_duplicate_nonfinite_or_nonobject_report_json_rejects(self):
        for raw in (b'{"retained_files":[],"retained_files":[]}', b'{"retained_files":NaN}',
                    b'[]', b'null', b'\xff', b'[' * 2000):
            with self.subTest(raw=raw[:40]), mock.patch.object(receipt, "verify_document") as semantic:
                self.make_zip(raw_report=raw)
                with self.assertRaises(ValueError):
                    self.check()
                semantic.assert_not_called()

    def test_zip_traversal_duplicate_symlink_and_special_entries_reject(self):
        symlink = zipfile.ZipInfo("outside/symlink")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        special = zipfile.ZipInfo("outside/fifo")
        special.create_system = 3
        special.external_attr = (stat.S_IFIFO | 0o600) << 16
        for entry in ("../escape", "/absolute", "a/../escape", "a//b", "C:/drive",
                      PREFIX + "/report.json", symlink, special):
            with self.subTest(entry=str(entry)), mock.patch.object(receipt, "verify_document") as semantic:
                self.make_zip(extra=[(entry, b"unsafe member")])
                with self.assertRaises(ValueError):
                    self.check()
                semantic.assert_not_called()

    def test_archive_file_cannot_shadow_a_parent_directory(self):
        self.make_zip(extra=[("outside", b"file"), ("outside/child", b"child")])
        with self.assertRaisesRegex(ValueError, "shadows a parent"):
            self.check()

    def test_crc_tamper_rejects_with_matching_tampered_zip_pin(self):
        self.make_zip()
        body = bytearray(self.path.read_bytes())
        with zipfile.ZipFile(self.path) as archive:
            item = archive.getinfo(PREFIX + "/helpers/inert.py")
            name_size, extra_size = struct.unpack_from("<HH", body, item.header_offset + 26)
            offset = item.header_offset + 30 + name_size + extra_size
        body[offset] ^= 1
        self.path.write_bytes(body)
        self.zip_sha256 = sha256(body)
        with self.assertRaisesRegex(ValueError, "invalid retained member payload"):
            self.check()

    def test_zip_comments_and_trailing_payload_are_outside_the_contract(self):
        self.make_zip()
        original = self.path.read_bytes()
        for body in (original + b"trailing", original[:-2] + b"\x01\x00x"):
            with self.subTest(tail=body[-12:]):
                self.path.write_bytes(body)
                self.zip_sha256 = sha256(body)
                with self.assertRaises(ValueError):
                    self.check()

    def test_changed_archive_during_semantics_cannot_return_success(self):
        self.make_zip()

        def mutate(document, read, *, expected_revision):
            result = self.synthetic_semantics(document, read, expected_revision=expected_revision)
            with self.path.open("ab") as stream:
                stream.write(b"changed during review")
            return result

        with mock.patch.object(receipt, "verify_document", side_effect=mutate), \
             self.assertRaisesRegex(ValueError, "original ZIP changed during its audit"):
            self.check()

    def test_local_archive_symlink_rejects(self):
        self.make_zip()
        alias = self.root / "alias.zip"
        alias.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError, "canonical without symlinks"):
            replay.replay_archive(alias, self.zip_sha256, expected_revision=REVISION,
                expected_receipt_sha256=self.receipt_sha256)

    def test_trusted_reader_drift_before_or_after_review_rejects(self):
        self.make_zip()
        for calls in ([[]], [replay.TRUSTED_READER_SOURCES, []]):
            with self.subTest(observations=len(calls)), \
                 mock.patch.object(replay, "_reader_sources", side_effect=calls), \
                 mock.patch.object(receipt, "verify_document", side_effect=self.synthetic_semantics), \
                 self.assertRaisesRegex(ValueError, "trusted dependency replay source changed"):
                self.check()

    def test_cache_bound_and_inventory_boundary_are_enforced_before_reads(self):
        self.make_zip()
        api = replay._archive_api()
        with api.ArchiveReader(self.path, self.zip_sha256) as archive:
            view = archive.view(PREFIX)
            read = replay.CachedPacket(view)
            with self.assertRaisesRegex(ValueError, "outside the selected packet inventory"):
                read("helpers/inert.py")
            with mock.patch.object(replay, "MAX_CACHE_BYTES", 1), \
                 self.assertRaisesRegex(ValueError, "requested read bound"):
                read("report.json")

    def test_cli_writes_complete_result_exclusively_and_preserves_existing_output(self):
        self.make_zip()
        target = self.root / "replay.json"
        argv = ["--archive", str(self.path), "--sha256", self.zip_sha256,
                "--source-revision", REVISION, "--dependency-receipt-sha256", self.receipt_sha256,
                "--output", str(target)]
        with mock.patch.object(receipt, "verify_document", side_effect=self.synthetic_semantics), \
             contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(replay.main(argv), 0)
        result = json.loads(target.read_text())
        self.assertEqual(result["dependency_receipt_sha256"], self.receipt_sha256)
        self.assertEqual(result["archive_read"]["archive"]["sha256"], self.zip_sha256)
        self.assertEqual(json.loads(stdout.getvalue())["native_execution"], "not_run")
        before = target.read_bytes()
        with mock.patch.object(receipt, "verify_document", side_effect=self.synthetic_semantics), \
             contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(replay.main(argv), 1)
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(json.loads(stdout.getvalue())["outcome"], "fail")

    def test_cli_validation_failure_has_no_success_flag_or_output(self):
        self.make_zip()
        target = self.root / "never-created.json"
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            status = replay.main(["--archive", str(self.path), "--sha256", self.zip_sha256,
                "--source-revision", REVISION, "--dependency-receipt-sha256", self.receipt_sha256,
                "--output", str(target)])
        self.assertEqual(status, 1)
        result = json.loads(stdout.getvalue())
        self.assertFalse(result["retained_consistency"])
        self.assertEqual(result["native_execution"], "not_run")
        self.assertFalse(target.exists())
        for name in contract.FALSE_CLAIMS:
            self.assertIs(result[name], False)


class DependencyArchiveHelperCacheTests(unittest.TestCase):
    def test_exact_source_pin_bypasses_matching_timestamp_bytecode_cache(self):
        managed = replay.managed_archive
        original = managed.ROOT / managed.archive_helpers.ARCHIVE_READER_PATH
        body = original.read_bytes()
        self.assertEqual(sha256(body), managed.archive_helpers.ARCHIVE_READER_SHA256)
        with tempfile.TemporaryDirectory(prefix="p06-dependency-cache-") as directory:
            root = Path(directory)
            source = root / managed.archive_helpers.ARCHIVE_READER_PATH
            source.parent.mkdir(parents=True)
            source.write_bytes(body)
            cached = Path(importlib.util.cache_from_source(str(source)))
            cached.parent.mkdir()
            code = compile("CACHE_SENTINEL = 'unverified bytecode'\n", str(source), "exec")
            info = source.stat()
            cached.write_bytes(importlib.util.MAGIC_NUMBER + struct.pack(
                "<III", 0, int(info.st_mtime) & 0xffffffff, info.st_size & 0xffffffff) + marshal.dumps(code))
            # Establish that the cache really is accepted by ordinary loading.
            spec = importlib.util.spec_from_file_location("dependency_cache_control", source)
            ordinary = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(ordinary)
            self.assertEqual(ordinary.CACHE_SENTINEL, "unverified bytecode")
            self.assertFalse(hasattr(ordinary, "ArchiveReader"))
            with mock.patch.object(managed, "ROOT", root), \
                 mock.patch.object(importlib.machinery.SourceFileLoader, "get_code",
                                   side_effect=AssertionError("unverified cache requested")), \
                 mock.patch.object(importlib.machinery.SourceFileLoader, "exec_module",
                                   side_effect=AssertionError("file-loader cache executed")):
                api = replay._archive_api()
            self.assertFalse(hasattr(api, "CACHE_SENTINEL"))
            self.assertTrue(callable(api.ArchiveReader))
            self.assertEqual(api.strict_json(b'{"inert":true}'), {"inert": True})


if __name__ == "__main__":
    unittest.main()
