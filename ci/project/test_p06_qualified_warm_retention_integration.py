# SPDX-License-Identifier: Apache-2.0
"""Synthetic package-to-restore integration; no encryption or native execution."""

import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import time
import unittest
import zipfile

import p06_qualified_warm_encrypt as producer
import p06_qualified_warm_pack as pack
import p06_qualified_warm_restore as restore
import p06_qualified_warm_retention as retention


REVISION = "b1" * 20
FALSE_CLAIMS = ("retained_code_executed", "origin_authenticated", "native_acceptance",
                "performance_acceptance", "phase_acceptance")


class RetentionPackagingIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-retention-integration-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()
        self.workspace = self.root / "workspace"
        self.evidence = self.workspace / "evidence"
        unfinished = producer._json_bytes({"state": "running", "outcome": "fail",
            "commands": [{"process_started": True, "cleanup_complete": False}]})
        self.evidence_files = {
            pack.runner.RECEIPT_PATH: producer._json_bytes({"state": "running", "outcome": "fail",
                "stages": [{"process_started": True, "cleanup_complete": False}]}),
            "qualified-warm/report.json": unfinished,
            "qualified-warm/.retention.lock": b"",
            "qualified-warm/output/incomplete.bin": bytes(range(256)),
            "qualified-warm/retained.py": b"raise RuntimeError('synthetic retained code must stay inert')\n",
            "dependency-build/.hidden/failed-build.log": b"synthetic failure\x00\xff\n",
        }
        for name, body in self.evidence_files.items():
            path = self.evidence / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        self.acquisition = self.root / "failed-acquisition"
        self.acquisition.mkdir()
        self.acquisition_bytes = b"synthetic acquisition stderr\xff\x00\n"
        (self.acquisition / "stdout-stderr.bin").write_bytes(self.acquisition_bytes)

    def package_partial(self, output):
        return pack.package_partial(source_dir=self.source, workspace_dir=self.workspace,
            output_dir=output, writers_finished=True,
            extra_roots={"failed-acquisition": self.acquisition})

    def plaintext_archive(self, input_dir):
        """Stream the actual producer's inventory, member headers, and verified readers."""
        deadline = time.monotonic() + producer.MAX_RUNTIME_SECONDS
        entries = producer._inventory(input_dir, deadline)
        manifest = producer._json_bytes({"schema_version": 1, "contract_id": producer.CONTRACT_ID,
            "expected_revision": REVISION,
            "directories": [name for name, entry in sorted(entries.items()) if entry.directory],
            "files": [{"path": name, "size_bytes": entry.size, "sha256": entry.sha256}
                      for name, entry in sorted(entries.items()) if not entry.directory]})
        path = self.root / "retained.tar"
        with path.open("xb") as output, tarfile.open(fileobj=output, mode="w|",
                format=tarfile.PAX_FORMAT, encoding="utf-8", errors="strict") as archive:
            for info, entry in producer._tar_members(entries, manifest):
                if entry is None:
                    archive.addfile(info, io.BytesIO(manifest))
                elif entry.directory:
                    archive.addfile(info)
                else:
                    reader = producer._VerifiedReader(input_dir, entry, deadline)
                    try:
                        archive.addfile(info, reader)
                        reader.verify()
                    finally:
                        reader.close()
        self.assertEqual(path.stat().st_size, producer._tar_size(entries, manifest))
        return path, manifest

    def tree(self, root):
        files, directories = {}, {""}
        for path in root.rglob("*"):
            name = path.relative_to(root).as_posix()
            if path.is_dir():
                directories.add(name)
            else:
                files[name] = path.read_bytes()
        return files, directories

    def assert_partial_packet(self, packet, receipt):
        self.assertEqual(json.loads((packet / pack.RECEIPT_NAME).read_bytes()), receipt)
        self.assertIs(receipt["packaging_passed"], True)
        self.assertIs(receipt["partial_attempt"], True)
        self.assertIs(receipt["complete_replay_original_created"], False)
        self.assertIs(receipt["writer_observations"]["finished_cleanup_records_verified"], False)
        self.assertTrue(receipt["writer_observations"]["unresolved"])
        self.assertFalse((packet / pack.ORIGINAL_NAME).exists())
        self.assertFalse((packet / pack.ENVELOPE_NAME).exists())
        expected = {"partial-attempt/evidence/" + name: body
                    for name, body in self.evidence_files.items()}
        expected["partial-attempt/additional-evidence/failed-acquisition/stdout-stderr.bin"] = \
            self.acquisition_bytes
        with zipfile.ZipFile(packet / pack.PARTIAL_NAME) as archive:
            self.assertEqual({name: archive.read(name) for name in archive.namelist()}, expected)

    def assert_roundtrip(self, input_dir):
        before = self.tree(input_dir)
        archive, manifest = self.plaintext_archive(input_dir)
        archive_bytes = archive.read_bytes()
        digest = hashlib.sha256(archive_bytes).hexdigest()
        inspected = retention.inspect_archive(archive, digest, expected_revision=REVISION)
        output = self.root / "restored"
        restored = restore.restore_archive(archive, digest,
            expected_revision=REVISION, output_dir=output)
        self.assertEqual(restored, dict(inspected, restoration_completed=True))
        self.assertEqual(inspected["outcome"], "pass")
        self.assertIs(inspected["retention_verified"], True)
        self.assertEqual(inspected["native_execution"], "not_run")
        for name in FALSE_CLAIMS:
            self.assertIs(inspected[name], False)
        self.assertEqual(inspected["file_count"], len(before[0]))
        self.assertEqual(inspected["directory_count"], len(before[1]))
        self.assertEqual(inspected["input_bytes"], sum(map(len, before[0].values())))
        self.assertEqual(self.tree(output / "private"), before)
        self.assertEqual((output / "manifest.json").read_bytes(), manifest)
        self.assertEqual({path.name for path in output.iterdir()}, {"manifest.json", "private"})
        self.assertEqual(self.tree(input_dir), before)
        self.assertEqual(archive.read_bytes(), archive_bytes)
        return output / "private"

    def assert_rejected_without_output(self, archive, code):
        # Bind the changed tar itself so rejection must also validate its manifest.
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        with self.assertRaisesRegex(retention.RetentionError, "^" + code + "$"):
            retention.inspect_archive(archive, digest, expected_revision=REVISION)
        output = self.root / "rejected-restore"
        with self.assertRaisesRegex(restore.RestoreError, "^retention-rejected$"):
            restore.restore_archive(archive, digest,
                expected_revision=REVISION, output_dir=output)
        self.assertFalse(output.exists())

    def test_direct_partial_packet_restores_exact_zip_and_incomplete_receipt(self):
        packet = self.root / "packet"
        receipt = self.package_partial(packet)
        original_zip = (packet / pack.PARTIAL_NAME).read_bytes()
        restored = self.assert_roundtrip(packet)
        self.assertEqual((restored / pack.PARTIAL_NAME).read_bytes(), original_zip)
        self.assert_partial_packet(restored, receipt)

    def test_hosted_retention_tree_preserves_packet_hidden_failure_bytes_and_empty_directory(self):
        selected = self.root / "retention"
        selected.mkdir()
        packet = selected / "packet"
        receipt = self.package_partial(packet)
        original_zip = (packet / pack.PARTIAL_NAME).read_bytes()
        (selected / "packaging.log").write_bytes(b"synthetic packaging output\x00\xff\n")
        (selected / "hosted-closeout.json").write_bytes(producer._json_bytes({
            "outcome": "fail", "native_execution": "not_run", "packaging_passed": True}))
        hidden = selected / ".failed-command"
        hidden.mkdir()
        (hidden / "stderr.bin").write_bytes(b"synthetic opaque failure\xff\xfe\x00\n")
        (hidden / "empty-after-interruption").mkdir()
        restored = self.assert_roundtrip(selected)
        self.assertEqual((restored / "packet" / pack.PARTIAL_NAME).read_bytes(), original_zip)
        self.assert_partial_packet(restored / "packet", receipt)
        self.assertTrue((restored / ".failed-command/empty-after-interruption").is_dir())
        self.assertEqual(json.loads((restored / "hosted-closeout.json").read_bytes())["outcome"], "fail")

    def test_changed_inner_zip_payload_is_rejected_before_creating_output(self):
        packet = self.root / "packet"
        self.package_partial(packet)
        before = self.tree(packet)
        archive, _ = self.plaintext_archive(packet)
        with tarfile.open(archive, mode="r:") as contents:
            member = contents.getmember("private/" + pack.PARTIAL_NAME)
        changed = bytearray(archive.read_bytes())
        changed[member.offset_data + member.size // 2] ^= 1
        archive.write_bytes(changed)
        self.assert_rejected_without_output(archive, "file-sha256")
        self.assertEqual(self.tree(packet), before)

    def test_undeclared_extra_member_is_rejected_before_creating_output(self):
        packet = self.root / "packet"
        self.package_partial(packet)
        before = self.tree(packet)
        archive, _ = self.plaintext_archive(packet)
        body = b"synthetic undeclared private output\x00\xff"
        with tarfile.open(archive, mode="a", format=tarfile.PAX_FORMAT,
                          encoding="utf-8", errors="strict") as contents:
            contents.addfile(producer._tar_info("private/.undeclared-failure.bin", size=len(body)),
                             io.BytesIO(body))
        self.assert_rejected_without_output(archive, "archive-format")
        self.assertEqual(self.tree(packet), before)


if __name__ == "__main__":
    unittest.main()
