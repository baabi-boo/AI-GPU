# SPDX-License-Identifier: Apache-2.0
"""Synthetic, offline restore fixtures; no ciphertext or native qualification."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

import p06_qualified_warm_restore as restore


REVISION = "a9" * 20
RETENTION_CONTRACT_ID = "p06-qualified-warm-encrypted-retention-v1"
FALSE_CLAIMS = ("retained_code_executed", "origin_authenticated", "native_acceptance",
                "performance_acceptance", "phase_acceptance")


class QualifiedWarmRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p06-restore-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.archive = self.root / "decrypted.PRIVATE.tar"
        self.output = self.root / "restored.PRIVATE"
        self.secret = b"PRIVATE-UNPUBLISHABLE-RAW-CONTENT\x00\xff"
        self.files = {".hidden/.lock": b"", "packet/original.PRIVATE.zip": bytes(range(256)),
            "packet/packaging.json": b'{"packaging_passed":true,"partial_attempt":true}',
            "private.raw": self.secret}
        self.make_archive(self.files, directories={"empty", ".hidden/empty"})

    def make_archive(self, files, *, directories=()):
        directories = set(directories) | {""}
        for name in set(files) | directories.copy():
            parts = name.split("/")
            directories.update("/".join(parts[:index]) for index in range(1, len(parts)))
        self.manifest = {"schema_version": 1, "contract_id": RETENTION_CONTRACT_ID,
            "expected_revision": REVISION, "directories": sorted(directories),
            "files": [{"path": name, "size_bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest()} for name, body in sorted(files.items())]}
        self.manifest_bytes = (json.dumps(self.manifest, sort_keys=True, separators=(",", ":"))
                               + "\n").encode()
        members = {"manifest.json": self.manifest_bytes,
                   **{"private" + ("/" + name if name else ""): None for name in directories},
                   **{"private/" + name: body for name, body in files.items()}}
        with tarfile.open(self.archive, "w", format=tarfile.PAX_FORMAT) as tar:
            for name, body in sorted(members.items()):
                info = tarfile.TarInfo(name)
                info.type = tarfile.DIRTYPE if body is None else tarfile.REGTYPE
                info.mode = 0o700 if body is None else 0o600
                info.size = 0 if body is None else len(body)
                info.mtime = 0
                tar.addfile(info, None if body is None else io.BytesIO(body))
        self.archive.chmod(0o600)
        self.digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def arguments(self, **updates):
        values = {"archive": self.archive, "expected_sha256": self.digest,
            "expected_revision": REVISION, "output_dir": self.output}
        values.update(updates)
        return values

    def run_restore(self, **updates):
        return restore.restore_archive(**self.arguments(**updates))

    def cli_arguments(self, operation="restore", **updates):
        values = {"archive": str(self.archive), "sha256": self.digest,
                  "expected-revision": REVISION}
        if operation == "restore":
            values["output-dir"] = str(self.output)
        values.update(updates)
        return [operation] + [item for name, value in values.items() for item in ("--" + name, value)]

    def assert_scope(self, report):
        self.assertEqual(report["native_execution"], "not_run")
        for name in FALSE_CLAIMS:
            self.assertIs(report[name], False)

    def assert_incomplete(self, output=None):
        output = output or self.output
        marker = output / restore.INCOMPLETE_NAME
        self.assertTrue(marker.is_file())
        document = json.loads(marker.read_bytes())
        self.assertEqual(document["outcome"], "incomplete")
        self.assertFalse(document["restoration_completed"])
        self.assert_scope(document)
        self.assertEqual(stat.S_IMODE(marker.stat().st_mode), 0o600)

    def summary(self, **updates):
        value = {"schema_version": 1, "contract_id": RETENTION_CONTRACT_ID,
            "expected_revision": REVISION, "outcome": "pass", "encryption_passed": True,
            "file_count": len(self.manifest["files"]),
            "directory_count": len(self.manifest["directories"]),
            "input_bytes": sum(item["size_bytes"] for item in self.manifest["files"]),
            "ciphertext_bytes": 1024, "ciphertext_sha256": "f" * 64}
        value.update(updates)
        path = self.root / "encryption-summary.json"
        path.write_text(json.dumps(value))
        return path

    def test_exact_manifest_hidden_files_empty_directories_and_private_modes(self):
        archive_before = self.archive.read_bytes()
        previous = os.umask(0)
        try:
            report = self.run_restore()
        finally:
            os.umask(previous)
        self.assertTrue(report["retention_verified"])
        self.assertTrue(report["restoration_completed"])
        self.assertEqual(report["archive_sha256"], self.digest)
        self.assertEqual(report["file_count"], len(self.files))
        self.assert_scope(report)
        self.assertEqual((self.output / "manifest.json").read_bytes(), self.manifest_bytes)
        self.assertEqual(self.archive.read_bytes(), archive_before)
        self.assertFalse((self.output / restore.INCOMPLETE_NAME).exists())
        actual = {path.relative_to(self.output / "private").as_posix(): path.read_bytes()
                  for path in (self.output / "private").rglob("*") if path.is_file()}
        self.assertEqual(actual, self.files)
        directories = {""} | {path.relative_to(self.output / "private").as_posix()
                            for path in (self.output / "private").rglob("*") if path.is_dir()}
        self.assertEqual(directories, set(self.manifest["directories"]))
        for path in [self.output, *self.output.rglob("*")]:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o600)

    def test_empty_tree_and_unicode_long_pax_paths_restore_without_extraction(self):
        for index, files in enumerate(({}, {"é" * 70 + "/.opaque": self.secret})):
            with self.subTest(index=index):
                self.make_archive(files, directories={"empty"})
                with mock.patch.object(tarfile.TarFile, "extract", side_effect=AssertionError), \
                     mock.patch.object(tarfile.TarFile, "extractall", side_effect=AssertionError), \
                     mock.patch.object(subprocess, "Popen", side_effect=AssertionError):
                    result = self.run_restore(output_dir=self.root / ("restored-" + str(index)))
                self.assert_scope(result)
                for name, body in files.items():
                    self.assertEqual((self.root / ("restored-" + str(index)) / "private" / name).read_bytes(),
                                     body)

    def test_short_writes_are_completed_without_changing_bytes(self):
        original = os.write

        def short_write(fd, body):
            return original(fd, body[:max(1, len(body) // 3)])

        with mock.patch.object(os, "write", side_effect=short_write):
            self.assertTrue(self.run_restore()["restoration_completed"])
        self.assertEqual((self.output / "private/private.raw").read_bytes(), self.secret)

    def test_malformed_late_payload_is_rejected_before_output_creation(self):
        with tarfile.open(self.archive, "r:") as tar:
            offset = tar.getmember("private/private.raw").offset_data
        body = bytearray(self.archive.read_bytes())
        body[offset] ^= 1
        self.archive.write_bytes(body)
        with self.assertRaises(restore.RestoreError):
            self.run_restore(expected_sha256=hashlib.sha256(body).hexdigest())
        self.assertFalse(self.output.exists())

    def test_wrong_digest_revision_and_summary_create_no_output(self):
        cases = ({"expected_sha256": "0" * 64}, {"expected_revision": "b" * 40},
                 {"summary": self.summary(file_count=999)})
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(restore.RestoreError):
                self.run_restore(**changes)
            self.assertFalse(self.output.exists())

    def test_matching_summary_is_input_only_and_does_not_authenticate_origin(self):
        summary = self.summary()
        before = summary.read_bytes()
        report = self.run_restore(summary=summary)
        self.assertTrue(report["summary_checked"])
        self.assert_scope(report)
        self.assertEqual(summary.read_bytes(), before)
        self.assertEqual({path.name for path in self.output.iterdir()}, {"manifest.json", "private"})

    def test_existing_directories_files_and_dangling_symlinks_are_untouched(self):
        existing = self.root / "existing"
        existing.mkdir()
        sentinel = existing / "sentinel"
        sentinel.write_bytes(self.secret)
        regular = self.root / "existing-file"
        regular.write_bytes(self.secret)
        dangling = self.root / "dangling"
        dangling.symlink_to(self.root / "missing")
        empty = self.root / "empty-output"
        empty.mkdir()
        for output in (existing, regular, dangling, empty):
            with self.subTest(output=output.name), self.assertRaises(restore.RestoreError):
                self.run_restore(output_dir=output)
        self.assertEqual(sentinel.read_bytes(), self.secret)
        self.assertEqual(regular.read_bytes(), self.secret)
        self.assertTrue(dangling.is_symlink())
        self.assertEqual(list(empty.iterdir()), [])

    def test_noncanonical_output_paths_and_input_overlap_are_rejected(self):
        for output in ("relative", "/", str(self.output) + "/", str(self.root) + "//new",
                       str(self.root) + "/./new", str(self.root) + "/../new",
                       str(self.output) + "\n", str(self.output) + "\\bad",
                       str(self.archive), str(self.archive) + "/child", str(self.root)):
            with self.subTest(output=output), self.assertRaises(restore.RestoreError):
                self.run_restore(output_dir=output)
        self.assertFalse(self.output.exists())
        self.assertEqual(hashlib.sha256(self.archive.read_bytes()).hexdigest(), self.digest)

    def test_symlink_ancestors_and_input_aliases_are_rejected_without_creation(self):
        link = self.root / "alias"
        link.symlink_to(self.root, target_is_directory=True)
        for changes in ({"output_dir": link / "new"}, {"archive": link / self.archive.name}):
            with self.subTest(changes=changes), self.assertRaises(restore.RestoreError):
                self.run_restore(**changes)
        self.assertFalse((self.root / "new").exists())
        self.assertFalse(self.output.exists())

    def test_copy_failure_and_interruption_retain_only_owned_incomplete_output(self):
        sentinel = self.root / "unrelated"
        sentinel.write_bytes(self.secret)
        for index, error in enumerate((OSError("PRIVATE-SECRET-PATH"), KeyboardInterrupt())):
            output = self.root / ("failed-" + str(index))
            with self.subTest(error=type(error).__name__), \
                 mock.patch.object(restore.retention.RetentionArchive, "copy_file", side_effect=error), \
                 self.assertRaises(restore.RestoreError):
                self.run_restore(output_dir=output)
            self.assert_incomplete(output)
        self.assertEqual(sentinel.read_bytes(), self.secret)

    def test_archive_mutation_after_copy_never_returns_success(self):
        original = restore.retention.RetentionArchive.copy_file
        mutated = False

        def change_archive(reader, name, fd):
            nonlocal mutated
            original(reader, name, fd)
            if not mutated:
                mutated = True
                with self.archive.open("ab") as stream:
                    stream.write(b"changed")

        with mock.patch.object(restore.retention.RetentionArchive, "copy_file", new=change_archive), \
             self.assertRaises(restore.RestoreError):
            self.run_restore()
        self.assert_incomplete()

    def test_changed_restored_bytes_and_unexpected_entries_are_detected(self):
        original = restore._verify_tree
        for index, change in enumerate(("bytes", "extra", "link", "directory")):
            output = self.root / ("changed-" + str(index))
            changed = False
            directory_identities = []

            def mutate(root_fd, directories, files):
                nonlocal changed
                if not changed:
                    changed = True
                    if change == "bytes":
                        (output / "private/private.raw").write_bytes(b"changed")
                    elif change == "extra":
                        (output / "private/extra").write_bytes(b"unexpected")
                    elif change == "link":
                        (output / "private/private.raw").unlink()
                        (output / "private/private.raw").symlink_to(self.archive)
                    else:
                        empty = output / "private/empty"
                        old_fd = os.open(empty, os.O_RDONLY | os.O_DIRECTORY)
                        held.callback(os.close, old_fd)
                        before = os.fstat(old_fd)
                        empty.rmdir()
                        empty.mkdir(mode=0o700)
                        after = empty.stat()
                        directory_identities.extend(((before.st_dev, before.st_ino),
                                                     (after.st_dev, after.st_ino)))
                return original(root_fd, directories, files)

            with self.subTest(change=change), ExitStack() as held:
                with mock.patch.object(restore, "_verify_tree", side_effect=mutate), \
                     self.assertRaises(restore.RestoreError) as caught:
                    self.run_restore(output_dir=output)
                if change == "directory":
                    self.assertEqual(len(directory_identities), 2)
                    self.assertNotEqual(*directory_identities)
                    self.assertEqual(caught.exception.code, "output-changed")
                self.assert_incomplete(output)

    def test_renamed_owned_root_never_cleans_up_an_unrelated_replacement(self):
        displaced = self.root / "displaced-owned"
        original = restore.retention.RetentionArchive.copy_file
        changed = False

        def replace_root(reader, name, fd):
            nonlocal changed
            original(reader, name, fd)
            if not changed:
                changed = True
                self.output.rename(displaced)
                self.output.mkdir()
                (self.output / "unrelated").write_bytes(self.secret)

        with mock.patch.object(restore.retention.RetentionArchive, "copy_file", new=replace_root), \
             self.assertRaises(restore.RestoreError):
            self.run_restore()
        self.assertEqual({path.name for path in self.output.iterdir()}, {"unrelated"})
        self.assertEqual((self.output / "unrelated").read_bytes(), self.secret)
        self.assert_incomplete(displaced)

    def test_failure_after_marker_removal_restores_incomplete_marker(self):
        original = restore._verify_tree

        def fail_after_marker(root_fd, directories, files):
            if restore.INCOMPLETE_NAME not in files:
                raise OSError("PRIVATE-FINAL-FAILURE")
            return original(root_fd, directories, files)

        with mock.patch.object(restore, "_verify_tree", side_effect=fail_after_marker), \
             self.assertRaises(restore.RestoreError):
            self.run_restore()
        self.assert_incomplete()

    def test_exclusive_file_creation_does_not_overwrite_a_raced_name(self):
        original = restore._new_file
        replaced = False

        def race(root_fd, directories, relative, size, digest, writer):
            nonlocal replaced
            if relative == "private/private.raw" and not replaced:
                replaced = True
                (self.output / relative).write_bytes(b"unrelated-raced-file")
            return original(root_fd, directories, relative, size, digest, writer)

        with mock.patch.object(restore, "_new_file", side_effect=race), \
             self.assertRaises(restore.RestoreError):
            self.run_restore()
        self.assertEqual((self.output / "private/private.raw").read_bytes(), b"unrelated-raced-file")
        self.assert_incomplete()

    def test_cli_invalid_arguments_and_exceptions_are_sanitized(self):
        cases = (["restore", "--PRIVATE-SECRET-PATH"],
                 self.cli_arguments(archive="/PRIVATE-SECRET-PATH"),
                 self.cli_arguments(**{"sha256": "PRIVATE-SECRET-PATH"}))
        for arguments in cases:
            stdout, stderr = io.StringIO(), io.StringIO()
            with self.subTest(arguments=arguments), redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(restore.main(arguments), 1)
            report = json.loads(stdout.getvalue())
            self.assertEqual(report["outcome"], "fail")
            self.assertFalse(report["restoration_completed"])
            self.assert_scope(report)
            self.assertEqual(stderr.getvalue(), "")
            self.assertNotIn("PRIVATE-SECRET-PATH", stdout.getvalue())
            self.assertNotIn(str(self.root), stdout.getvalue())

    def test_cli_copy_failure_is_sanitized_and_retains_partial_bytes(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(restore.retention.RetentionArchive, "copy_file",
                               side_effect=OSError("PRIVATE-SECRET-PATH")), \
             redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(restore.main(self.cli_arguments()), 1)
        self.assertNotIn("PRIVATE-SECRET-PATH", stdout.getvalue() + stderr.getvalue())
        self.assertNotIn(str(self.root), stdout.getvalue() + stderr.getvalue())
        self.assertFalse(json.loads(stdout.getvalue())["retention_verified"])
        self.assert_incomplete()

    def test_direct_cli_from_outside_checkout_inspects_then_restores(self):
        script = Path(restore.__file__).resolve()
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        for operation in ("inspect", "restore"):
            with self.subTest(operation=operation):
                completed = subprocess.run([sys.executable, str(script), *self.cli_arguments(operation)],
                    cwd=self.root, env=environment, capture_output=True, text=True, timeout=30)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                self.assertEqual(completed.stderr, "")
                report = json.loads(completed.stdout)
                self.assertEqual(report["outcome"], "pass")
                self.assert_scope(report)
                self.assertNotIn(str(self.root), completed.stdout)
                self.assertNotIn("private.raw", completed.stdout)
                self.assertNotIn("PRIVATE-UNPUBLISHABLE", completed.stdout)
                if operation == "inspect":
                    self.assertFalse(self.output.exists())
                else:
                    self.assertTrue(report["restoration_completed"])

    def test_direct_cli_does_not_cache_helpers_without_bytecode_environment(self):
        environment = dict(os.environ, PYTHONPYCACHEPREFIX=str(self.root / "python-cache"))
        environment.pop("PYTHONDONTWRITEBYTECODE", None)
        completed = subprocess.run([sys.executable, str(Path(restore.__file__).resolve()),
                                    *self.cli_arguments("inspect")], cwd=self.root, env=environment,
                                   capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(list((self.root / "python-cache").rglob("p06_qualified_warm_*.pyc")), [])


if __name__ == "__main__":
    unittest.main()
