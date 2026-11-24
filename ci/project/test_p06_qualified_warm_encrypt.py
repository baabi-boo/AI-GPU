# SPDX-License-Identifier: Apache-2.0
"""Offline orchestration/disclosure fixtures; fake age is NOT cryptographic proof.

Every test runs without downloading age or conditionally skipping. A controlled
subprocess records the private tar input and emits deterministic framed bytes.
Real external age roundtrips are separately recorded development evidence.
"""

from contextlib import redirect_stderr, redirect_stdout
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
import time
import unittest
from unittest import mock

import p06_qualified_warm_encrypt as encrypt


RECIPIENT = "age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8p"
REVISION = "e8e73347" + "0" * 32
PUBLIC_FIELDS = {"schema_version", "contract_id", "expected_revision", "outcome", "encryption_passed",
                 "file_count", "directory_count", "input_bytes", "ciphertext_bytes", "ciphertext_sha256"}


class EncryptedRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p06-encrypt-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "private-packet"
        self.source.mkdir(mode=0o700)
        self.output = self.root / "public-output"
        self.private = Path(str(self.output) + encrypt.PRIVATE_SUFFIX)
        self.binary = self.root / "age-fixture"
        self.capture = self.root / "captured.PRIVATE.tar"
        self.audit = self.root / "child.PRIVATE.json"
        self.secret = b"PRIVATE-UNPUBLISHABLE-RAW-CONTENT\x00\xff"
        self.put("private.raw", self.secret)
        self.put(".retention.lock", b"")
        self.put(".hidden/subdir/.opaque", bytes(range(256)))
        (self.source / "empty").mkdir()
        self.make_age()

    def put(self, name, body):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        path.chmod(0o600)
        return path

    def make_age(self, mode="success"):
        # This executable is an explicit test double. Its output is synthetic
        # age-shaped data, never called an encryption or decryption implementation.
        script = f'''#!{sys.executable}
import json, os, pathlib, subprocess, sys, time
mode = {mode!r}
audit = pathlib.Path({str(self.audit)!r})
capture = pathlib.Path({str(self.capture)!r})
source = pathlib.Path({str(self.source)!r})
record = {{"argv": sys.argv[1:], "env": dict(os.environ), "pid": os.getpid()}}
if mode == "descendant":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    record["child_pid"] = child.pid
with os.fdopen(os.open(audit, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
    json.dump(record, stream)
if mode in ("sleep", "descendant"):
    time.sleep(30)
if mode == "stderr-overflow":
    os.write(2, b"PRIVATE-STDERR-SECRET" * 4096)
if mode == "stdout-overflow":
    for _ in range(100):
        os.write(1, b"X" * 65536)
plain = sys.stdin.buffer.read()
with os.fdopen(os.open(capture, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
    stream.write(plain)
if mode == "nonzero":
    os.write(2, b"PRIVATE-STDERR-SECRET /private/machine/path ?token=PRIVATE_TOKEN")
    os.write(1, b"PRIVATE-STDOUT-SECRET")
    sys.exit(7)
if mode == "mutate":
    (source / "private.raw").write_bytes(b"changed after reading")
if mode == "add-hidden":
    (source / ".late-secret").write_bytes(b"late private evidence")
if mode == "plaintext":
    sys.stdout.buffer.write(plain)
    sys.exit(0)
if mode == "empty":
    sys.exit(0)
header = b"age-encryption.org/v1\\n-> X25519 " + b"A" * 43 + b"\\n" + b"A" * 43 + b"\\n--- " + b"A" * 43 + b"\\n"
length = len(plain) + 16 + ((len(plain) + 65535) // 65536) * 16
if mode == "truncated":
    length -= 1
if mode == "bad-stanza":
    header = header.replace(b"X25519", b"scrypt")
sys.stdout.buffer.write(header + b"\\xa5" * length)
'''
        self.binary.write_text(script)
        self.binary.chmod(0o700)

    def arguments(self, **updates):
        values = dict(input_dir=self.source, output_dir=self.output, recipient=RECIPIENT,
                      age_binary=str(self.binary), expected_revision=REVISION)
        values.update(updates)
        return values

    def run_encrypt(self, **updates):
        return encrypt.encrypt_private_directory(**self.arguments(**updates))

    def source_bytes(self, source=None):
        source = source or self.source
        return {path.relative_to(source).as_posix(): path.read_bytes()
                for path in source.rglob("*") if path.is_file()}

    def verify_captured_tar(self, expected):
        with tarfile.open(self.capture, "r:") as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            self.assertEqual(len(names), len(set(names)))
            self.assertEqual(names[0], encrypt.MANIFEST_NAME)
            manifest = json.load(archive.extractfile(encrypt.MANIFEST_NAME))
            files = {member.name.removeprefix("private/"): archive.extractfile(member).read()
                     for member in members if member.isfile() and member.name != encrypt.MANIFEST_NAME}
            self.assertEqual(files, expected)
            self.assertEqual(manifest["expected_revision"], REVISION)
            self.assertEqual(manifest["files"], [{"path": name, "size_bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest()} for name, body in sorted(expected.items())])
            for member in members:
                self.assertTrue(member.isfile() or member.isdir())
                self.assertEqual(member.mode, 0o700 if member.isdir() else 0o600)
            self.assertEqual({member.name.removeprefix("private").removeprefix("/")
                              for member in members if member.isdir()}, set(manifest["directories"]))
        return manifest

    def assert_failed_public(self):
        self.assertFalse((self.output / encrypt.CIPHERTEXT_NAME).exists())
        if self.output.exists():
            self.assertEqual({path.name for path in self.output.iterdir()}, {encrypt.SUMMARY_NAME})
            summary = json.loads((self.output / encrypt.SUMMARY_NAME).read_bytes())
            self.assertFalse(summary["encryption_passed"])
            self.assertEqual(summary["outcome"], "fail")
            self.assertEqual(set(summary), PUBLIC_FIELDS)
            for forbidden in (str(self.source), str(self.binary), RECIPIENT, self.secret.decode("latin1")):
                self.assertNotIn(forbidden, json.dumps(summary))

    def test_whole_opaque_directory_hidden_bytes_empty_dirs_and_exact_manifest(self):
        original = self.source_bytes()
        summary = self.run_encrypt()
        self.assertEqual(self.source_bytes(), original)
        manifest = self.verify_captured_tar(original)
        self.assertIn("empty", manifest["directories"])
        self.assertTrue(summary["encryption_passed"])
        self.assertEqual(set(summary), PUBLIC_FIELDS)
        self.assertEqual(summary["file_count"], len(original))
        self.assertEqual(summary["input_bytes"], sum(map(len, original.values())))
        self.assertEqual({path.name for path in self.output.iterdir()},
                         {encrypt.CIPHERTEXT_NAME, encrypt.SUMMARY_NAME})
        cipher = (self.output / encrypt.CIPHERTEXT_NAME).read_bytes()
        self.assertEqual(summary["ciphertext_sha256"], hashlib.sha256(cipher).hexdigest())
        self.assertEqual(summary["ciphertext_bytes"], len(cipher))
        self.assertNotIn(self.secret, cipher)
        self.assertEqual(json.loads((self.output / encrypt.SUMMARY_NAME).read_bytes()), summary)
        self.assertEqual({path.name for path in self.private.iterdir()}, {encrypt.STDERR_NAME})

    def test_no_plaintext_tar_is_created_in_either_output_directory(self):
        self.run_encrypt()
        for directory in (self.output, self.private):
            for path in directory.iterdir():
                self.assertNotIn(self.secret, path.read_bytes())
                self.assertNotIn(b"ustar", path.read_bytes())

    def test_owner_only_modes_even_with_permissive_umask(self):
        previous = os.umask(0)
        try:
            self.make_age("nonzero")
            with self.assertRaises(encrypt.EncryptionError):
                self.run_encrypt()
        finally:
            os.umask(previous)
        for directory in (self.output, self.private):
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            for path in directory.iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_strict_public_recipient_validation_precedes_any_files_or_process(self):
        bad = (None, "", "-p", "AGE-SECRET-KEY-1SECRET", "age1plugin1" + "q" * 52,
               "ssh-ed25519 AAAA", "https://secret.example/?token=PRIVATE_TOKEN", RECIPIENT.upper(),
               RECIPIENT + "\n", RECIPIENT + " " + RECIPIENT, RECIPIENT[:-1] + "q")
        self.assertEqual(encrypt.validate_recipient(RECIPIENT), RECIPIENT)
        for value in bad:
            with self.subTest(value=value), self.assertRaises(encrypt.EncryptionError):
                self.run_encrypt(recipient=value)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.private.exists())
        self.assertFalse(self.audit.exists())

    def test_every_single_character_checksum_substitution_is_rejected(self):
        for position in range(4, len(RECIPIENT)):
            replacement = "q" if RECIPIENT[position] != "q" else "p"
            changed = RECIPIENT[:position] + replacement + RECIPIENT[position + 1:]
            with self.subTest(position=position), self.assertRaises(encrypt.EncryptionError):
                encrypt.validate_recipient(changed)

    def test_revision_cannot_inject_public_paths_or_arbitrary_content(self):
        for value in (True, "g" * 40, REVISION.upper(), "PRIVATE_TOKEN", "/private/machine/path"):
            with self.subTest(value=value), self.assertRaises(encrypt.EncryptionError):
                self.run_encrypt(expected_revision=value)
        self.assertFalse(self.output.exists())

    def test_binary_environment_and_arguments_are_a_fixed_allowlist(self):
        with mock.patch.dict(os.environ, {"AGE_PLUGIN_PATH": "PRIVATE_TOKEN", "LD_PRELOAD": "secret.so",
                                          "SECRET_URL": "https://private/?token=PRIVATE_TOKEN"}):
            self.run_encrypt()
        child = json.loads(self.audit.read_bytes())
        self.assertEqual(child["argv"], ["--encrypt", "--recipient", RECIPIENT])
        # Python may insert LC_CTYPE for its own locale coercion; the parent
        # supplies exactly SAFE_ENV and never forwards the ambient variables.
        self.assertTrue(set(child["env"]) <= set(encrypt.SAFE_ENV) | {"LC_CTYPE"})
        self.assertNotIn("PRIVATE_TOKEN", json.dumps(child["env"]))

    def test_missing_binary_and_binary_aliases_reject_before_output_creation(self):
        alias = self.root / "age-alias"
        alias.symlink_to(self.binary)
        hard = self.root / "age-hardlink"
        for binary in (str(self.root / "missing-age"), str(alias)):
            with self.subTest(binary=binary), self.assertRaises((OSError, ValueError)):
                self.run_encrypt(age_binary=binary)
        os.link(self.binary, hard)
        with self.assertRaises(encrypt.EncryptionError):
            self.run_encrypt(age_binary=str(hard))
        self.assertFalse(self.output.exists())

    def test_retained_input_cannot_be_selected_as_executable(self):
        trap = self.put("must-never-execute", b"#!/bin/sh\nexit 0\n")
        trap.chmod(0o700)
        with self.assertRaisesRegex(encrypt.EncryptionError, "overlap"):
            self.run_encrypt(age_binary=str(trap))
        self.assertFalse(self.output.exists())

    def test_fresh_output_and_private_sibling_are_required_without_overwrite(self):
        for directory in (self.output, self.private):
            with self.subTest(directory=directory.name):
                directory.mkdir()
                marker = directory / "do-not-overwrite"
                marker.write_bytes(self.secret)
                with self.assertRaises(encrypt.EncryptionError):
                    self.run_encrypt()
                self.assertEqual(marker.read_bytes(), self.secret)
                marker.unlink()
                directory.rmdir()
        self.assertFalse(self.audit.exists())

    def test_reusing_success_output_does_not_change_any_bytes(self):
        self.run_encrypt()
        before = {path.name: path.read_bytes() for path in self.output.iterdir()}
        with self.assertRaises(encrypt.EncryptionError):
            self.run_encrypt()
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.output.iterdir()})

    def test_publication_rejection_preserves_a_foreign_summary(self):
        original = encrypt._inventory
        calls = 0
        marker = b"unrelated output owner"
        def add_output(root, deadline):
            nonlocal calls
            result = original(root, deadline)
            calls += 1
            if calls == 2:
                (self.output / encrypt.SUMMARY_NAME).write_bytes(marker)
            return result
        with mock.patch.object(encrypt, "_inventory", side_effect=add_output):
            with self.assertRaisesRegex(encrypt.EncryptionError, "public-output-changed"):
                self.run_encrypt()
        self.assertEqual((self.output / encrypt.SUMMARY_NAME).read_bytes(), marker)
        self.assertFalse((self.output / encrypt.CIPHERTEXT_NAME).exists())
        self.assertTrue((self.private / encrypt.INCOMPLETE_NAME).exists())

    def test_summary_collision_after_ciphertext_link_does_not_clobber(self):
        original = encrypt.os.link
        marker = b"unrelated output owner"
        def collide(*args, **kwargs):
            original(*args, **kwargs)
            (self.output / encrypt.SUMMARY_NAME).write_bytes(marker)
        with mock.patch.object(encrypt.os, "link", side_effect=collide):
            with self.assertRaises(FileExistsError):
                self.run_encrypt()
        self.assertEqual((self.output / encrypt.SUMMARY_NAME).read_bytes(), marker)
        self.assertFalse((self.output / encrypt.CIPHERTEXT_NAME).exists())
        self.assertTrue((self.private / encrypt.INCOMPLETE_NAME).exists())

    def test_summary_write_failure_revokes_owned_partial_publication(self):
        original = encrypt._write_all
        failed = False
        def interrupt_summary(stream, body):
            nonlocal failed
            if not failed and b'"encryption_passed":true' in body:
                failed = True
                stream.write(body[:12])
                raise OSError("summary-write-failed")
            return original(stream, body)
        with mock.patch.object(encrypt, "_write_all", side_effect=interrupt_summary):
            with self.assertRaisesRegex(OSError, "summary-write-failed"):
                self.run_encrypt()
        self.assertTrue(failed)
        self.assert_failed_public()
        self.assertTrue((self.private / encrypt.INCOMPLETE_NAME).exists())

    def test_ciphertext_link_completion_then_interrupt_revokes_owned_publication(self):
        original = encrypt.os.link
        retained = []
        def interrupt_after_link(source, target, **kwargs):
            original(source, target, **kwargs)
            if target == encrypt.CIPHERTEXT_NAME:
                retained.append((self.output / target).read_bytes())
                raise KeyboardInterrupt("after-ciphertext-link")
        with mock.patch.object(encrypt.os, "link", side_effect=interrupt_after_link):
            with self.assertRaisesRegex(KeyboardInterrupt, "after-ciphertext-link"):
                self.run_encrypt()
        self.assertEqual(len(retained), 1)
        self.assert_failed_public()
        self.assertEqual((self.private / encrypt.INCOMPLETE_NAME).read_bytes(), retained[0])

    def test_success_summary_write_completion_then_interrupt_cannot_leave_public_pass(self):
        original = encrypt._write_json
        retained = []
        def interrupt_after_write(directory_fd, name, document):
            identity = original(directory_fd, name, document)
            if document.get("encryption_passed"):
                retained.append((self.private / encrypt.INCOMPLETE_NAME).read_bytes())
                raise KeyboardInterrupt("after-success-summary-write")
            return identity
        with mock.patch.object(encrypt, "_write_json", side_effect=interrupt_after_write):
            with self.assertRaisesRegex(KeyboardInterrupt, "after-success-summary-write"):
                self.run_encrypt()
        self.assertEqual(len(retained), 1)
        self.assert_failed_public()
        self.assertEqual((self.private / encrypt.INCOMPLETE_NAME).read_bytes(), retained[0])

    def test_summary_link_completion_then_interrupt_withdraws_pass_before_ciphertext(self):
        original_link, original_unlink = encrypt.os.link, encrypt.os.unlink
        def interrupt_after_link(source, target, **kwargs):
            original_link(source, target, **kwargs)
            if target == encrypt.SUMMARY_NAME:
                raise KeyboardInterrupt("after-summary-link")
        def observe_unlink(name, **kwargs):
            if name == encrypt.CIPHERTEXT_NAME:
                self.assertFalse((self.output / encrypt.SUMMARY_NAME).exists())
                self.assertTrue((self.private / encrypt.INCOMPLETE_NAME).exists())
            return original_unlink(name, **kwargs)
        with mock.patch.object(encrypt.os, "link", side_effect=interrupt_after_link), \
                mock.patch.object(encrypt.os, "unlink", side_effect=observe_unlink):
            with self.assertRaisesRegex(KeyboardInterrupt, "after-summary-link"):
                self.run_encrypt()
        self.assert_failed_public()
        self.assertTrue((self.private / encrypt.INCOMPLETE_NAME).exists())

    def test_unwithdrawable_owned_success_summary_keeps_its_ciphertext(self):
        original_sync, original_unlink = encrypt.os.fsync, encrypt.os.unlink
        def fail_directory_sync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("publication-sync-failed")
            return original_sync(fd)
        def fail_summary_unlink(name, **kwargs):
            if name == encrypt.SUMMARY_NAME:
                raise OSError("summary-withdrawal-failed")
            return original_unlink(name, **kwargs)
        with mock.patch.object(encrypt.os, "fsync", side_effect=fail_directory_sync), \
                mock.patch.object(encrypt.os, "unlink", side_effect=fail_summary_unlink):
            with self.assertRaisesRegex(OSError, "publication-sync-failed"):
                self.run_encrypt()
        summary = json.loads((self.output / encrypt.SUMMARY_NAME).read_bytes())
        cipher = (self.output / encrypt.CIPHERTEXT_NAME).read_bytes()
        self.assertTrue(summary["encryption_passed"])
        self.assertEqual(summary["ciphertext_sha256"], hashlib.sha256(cipher).hexdigest())
        self.assertEqual(summary["ciphertext_bytes"], len(cipher))
        self.assertEqual((self.private / encrypt.INCOMPLETE_NAME).read_bytes(), cipher)
        diagnostic = json.loads((self.private / encrypt.DIAGNOSTIC_NAME).read_bytes())
        self.assertFalse(diagnostic["publication_committed"])

    def test_private_ciphertext_unlink_interruption_preserves_committed_public_pair(self):
        original = encrypt.os.unlink
        original_inputs = self.source_bytes()
        for after in (False, True):
            with self.subTest(unlink_completed=after):
                def interrupt_private_unlink(name, **kwargs):
                    if name == encrypt.INCOMPLETE_NAME:
                        if after:
                            original(name, **kwargs)
                        raise KeyboardInterrupt("private-ciphertext-cleanup")
                    return original(name, **kwargs)
                with mock.patch.object(encrypt.os, "unlink", side_effect=interrupt_private_unlink):
                    with self.assertRaisesRegex(KeyboardInterrupt, "private-ciphertext-cleanup"):
                        self.run_encrypt()
                summary = json.loads((self.output / encrypt.SUMMARY_NAME).read_bytes())
                cipher = (self.output / encrypt.CIPHERTEXT_NAME).read_bytes()
                self.assertTrue(summary["encryption_passed"])
                self.assertEqual(summary["ciphertext_sha256"], hashlib.sha256(cipher).hexdigest())
                self.assertEqual(summary["ciphertext_bytes"], len(cipher))
                self.assertEqual((self.private / encrypt.INCOMPLETE_NAME).exists(), not after)
                self.assertEqual(self.source_bytes(), original_inputs)
                diagnostic = json.loads((self.private / encrypt.DIAGNOSTIC_NAME).read_bytes())
                self.assertTrue(diagnostic["publication_committed"])
                self._remove_outputs()

    def test_rollback_preserves_last_ciphertext_when_private_path_is_lost_or_replaced(self):
        original = encrypt.os.link
        marker = b"unrelated private output owner"
        for replaced in (False, True):
            with self.subTest(replaced=replaced):
                retained = []
                def fail_summary_link(source, target, **kwargs):
                    if target == encrypt.SUMMARY_NAME:
                        path = self.private / encrypt.INCOMPLETE_NAME
                        retained.append(path.read_bytes())
                        path.unlink()
                        if replaced:
                            path.write_bytes(marker)
                        raise OSError("summary-publication-failed")
                    return original(source, target, **kwargs)
                with mock.patch.object(encrypt.os, "link", side_effect=fail_summary_link):
                    with self.assertRaisesRegex(OSError, "summary-publication-failed"):
                        self.run_encrypt()
                self.assertEqual(len(retained), 1)
                self.assertEqual((self.output / encrypt.CIPHERTEXT_NAME).read_bytes(), retained[0])
                self.assertFalse(json.loads((self.output / encrypt.SUMMARY_NAME).read_bytes())["encryption_passed"])
                if replaced:
                    self.assertEqual((self.private / encrypt.INCOMPLETE_NAME).read_bytes(), marker)
                self._remove_outputs()

    def test_publication_rollback_preserves_replaced_file_identities(self):
        original = encrypt.os.fsync
        marker = b"unrelated output owner"
        def replace_on_directory_sync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                (self.output / encrypt.SUMMARY_NAME).rename(self.root / "original-summary")
                (self.output / encrypt.CIPHERTEXT_NAME).unlink()
                for name in (encrypt.SUMMARY_NAME, encrypt.CIPHERTEXT_NAME):
                    (self.output / name).write_bytes(marker)
                raise OSError("publication-sync-failed")
            return original(fd)
        with mock.patch.object(encrypt.os, "fsync", side_effect=replace_on_directory_sync):
            with self.assertRaisesRegex(OSError, "publication-sync-failed"):
                self.run_encrypt()
        for name in (encrypt.SUMMARY_NAME, encrypt.CIPHERTEXT_NAME):
            self.assertEqual((self.output / name).read_bytes(), marker)
        self.assertNotEqual((self.private / encrypt.INCOMPLETE_NAME).read_bytes(), marker)

    def test_observed_public_replacement_cannot_commit_and_delete_private_ciphertext(self):
        original = encrypt.os.fsync
        marker = b"unrelated output owner"
        retained = []
        def replace_on_directory_sync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                path = self.output / encrypt.CIPHERTEXT_NAME
                retained.append(path.read_bytes())
                path.unlink()
                path.write_bytes(marker)
            return original(fd)
        with mock.patch.object(encrypt.os, "fsync", side_effect=replace_on_directory_sync):
            with self.assertRaisesRegex(encrypt.EncryptionError, "public-output-changed"):
                self.run_encrypt()
        self.assertEqual(len(retained), 1)
        self.assertEqual((self.output / encrypt.CIPHERTEXT_NAME).read_bytes(), marker)
        self.assertEqual((self.private / encrypt.INCOMPLETE_NAME).read_bytes(), retained[0])
        self.assertFalse(json.loads((self.output / encrypt.SUMMARY_NAME).read_bytes())["encryption_passed"])

    def test_overlap_and_noncanonical_paths_are_rejected(self):
        for output in (self.source, self.source / "output", self.root,
                       str(self.root) + "/x/../output", str(self.root) + "//output", str(self.root) + "/./output"):
            with self.subTest(output=str(output)), self.assertRaises((OSError, ValueError)):
                self.run_encrypt(output_dir=output)
        with self.assertRaises(encrypt.EncryptionError):
            self.run_encrypt(input_dir="relative-input")
        self.assertFalse(self.audit.exists())

    def test_symlink_ancestors_on_inputs_and_output_parent_are_rejected(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        for changes in ({"input_dir": alias / self.source.name}, {"output_dir": alias / "other-output"}):
            with self.subTest(changes=changes), self.assertRaises(OSError):
                self.run_encrypt(**changes)
        self.assertFalse(self.audit.exists())

    def test_symlink_and_hardlink_and_special_file_never_reach_age(self):
        for kind in ("file-link", "directory-link", "hardlink", "fifo"):
            with self.subTest(kind=kind):
                item = self.source / "unsafe"
                if kind == "file-link":
                    item.symlink_to(self.source / "private.raw")
                elif kind == "directory-link":
                    item.symlink_to(self.source / "empty", target_is_directory=True)
                elif kind == "hardlink":
                    os.link(self.source / "private.raw", item)
                else:
                    os.mkfifo(item)
                with self.assertRaises(encrypt.EncryptionError):
                    self.run_encrypt()
                self.assert_failed_public()
                self.assertFalse(self.audit.exists())
                item.unlink()
                self._remove_outputs()

    def _remove_outputs(self):
        for directory in (self.output, self.private):
            if directory.exists():
                for path in directory.iterdir():
                    path.unlink()
                directory.rmdir()
        for path in (self.audit, self.capture):
            if path.exists():
                path.unlink()

    def test_nonportable_and_case_alias_names_are_rejected(self):
        for name in ("bad\\name", "bad:name", "bad\nname", "e\u0301", "PRIVATE.RAW"):
            with self.subTest(name=name):
                item = self.put(name, self.secret)
                with self.assertRaises((UnicodeError, ValueError)):
                    self.run_encrypt()
                self.assert_failed_public()
                self.assertFalse(self.audit.exists())
                item.unlink()
                self._remove_outputs()

    def test_age_nonzero_and_raw_diagnostics_are_private(self):
        self.make_age("nonzero")
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = encrypt.main(["--input-dir", str(self.source), "--output-dir", str(self.output),
                "--recipient", RECIPIENT, "--age-binary", str(self.binary), "--expected-revision", REVISION])
        self.assertEqual(code, 1)
        self.assertEqual(stderr.getvalue(), "")
        public = json.loads(stdout.getvalue())
        self.assertEqual(set(public), PUBLIC_FIELDS)
        self.assertNotIn("PRIVATE", stdout.getvalue())
        self.assert_failed_public()
        self.assertIn(b"PRIVATE-STDERR-SECRET", (self.private / encrypt.STDERR_NAME).read_bytes())
        self.assertIn(b"PRIVATE-STDOUT-SECRET", (self.private / encrypt.INCOMPLETE_NAME).read_bytes())
        receipt = json.loads((self.private / encrypt.DIAGNOSTIC_NAME).read_bytes())
        self.assertTrue(receipt["cleanup_complete"])
        self.assertFalse(receipt["plaintext_publication_authorized"])

    def test_cli_argument_errors_do_not_echo_sensitive_user_text(self):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = encrypt.main(["--unknown", "https://private.example/?token=PRIVATE_TOKEN"])
        self.assertEqual(result, 1)
        self.assertEqual(errors.getvalue(), "")
        self.assertNotIn("PRIVATE_TOKEN", output.getvalue())
        self.assertFalse(json.loads(output.getvalue())["encryption_passed"])

    def test_successful_exit_cannot_publish_plaintext_empty_truncated_or_wrong_format(self):
        for mode in ("plaintext", "empty", "truncated", "bad-stanza"):
            with self.subTest(mode=mode):
                self.make_age(mode)
                with self.assertRaises(encrypt.EncryptionError):
                    self.run_encrypt()
                self.assert_failed_public()
                self._remove_outputs()

    def test_stdout_is_bounded_and_never_published_on_overflow(self):
        self.make_age("stdout-overflow")
        with self.assertRaisesRegex(encrypt.EncryptionError, "ciphertext-byte-limit"):
            self.run_encrypt()
        self.assert_failed_public()
        self.assertLess((self.private / encrypt.INCOMPLETE_NAME).stat().st_size, 65536)
        self._assert_child_not_running()

    def test_stderr_bound_retains_prefix_privately_and_kills_process(self):
        self.make_age("stderr-overflow")
        with mock.patch.object(encrypt, "MAX_STDERR_BYTES", 1024):
            with self.assertRaisesRegex(encrypt.EncryptionError, "stderr-byte-limit"):
                self.run_encrypt()
        self.assert_failed_public()
        self.assertEqual((self.private / encrypt.STDERR_NAME).stat().st_size, 1024)
        self._assert_child_not_running()

    def _assert_child_not_running(self, field="pid"):
        pid = json.loads(self.audit.read_bytes())[field]
        state = Path(f"/proc/{pid}/stat")
        if state.exists():
            self.assertEqual(state.read_text().split(") ", 1)[1].split()[0], "Z")

    def test_runtime_limit_reaps_child_and_retains_failure(self):
        self.make_age("sleep")
        start = time.monotonic()
        with mock.patch.object(encrypt, "MAX_RUNTIME_SECONDS", 0.25):
            with self.assertRaisesRegex(encrypt.EncryptionError, "runtime-limit"):
                self.run_encrypt()
        self.assertLess(time.monotonic() - start, 3)
        self.assert_failed_public()
        self._assert_child_not_running()

    def test_runtime_cleanup_signals_descendants_in_the_process_group(self):
        self.make_age("descendant")
        with mock.patch.object(encrypt, "MAX_RUNTIME_SECONDS", 0.25):
            with self.assertRaisesRegex(encrypt.EncryptionError, "runtime-limit"):
                self.run_encrypt()
        self.assert_failed_public()
        self._assert_child_not_running()
        self._assert_child_not_running("child_pid")

    def test_changed_bytes_and_late_hidden_files_revoke_ciphertext_publication(self):
        for mode in ("mutate", "add-hidden"):
            with self.subTest(mode=mode):
                self.make_age(mode)
                with self.assertRaisesRegex(encrypt.EncryptionError, "source-changed"):
                    self.run_encrypt()
                self.assert_failed_public()
                self._remove_outputs()

    def test_file_and_total_byte_bounds_precede_age(self):
        for name, limit in (("MAX_FILE_BYTES", 1), ("MAX_INPUT_BYTES", 1), ("MAX_ENTRIES", 1),
                            ("MAX_MANIFEST_BYTES", 1)):
            with self.subTest(bound=name), mock.patch.object(encrypt, name, limit):
                with self.assertRaises(encrypt.EncryptionError):
                    self.run_encrypt()
            self.assertFalse(self.audit.exists())
            self.assertFalse((self.output / encrypt.CIPHERTEXT_NAME).exists())
            self._remove_outputs()

    def test_retention_storage_guard_is_distinct_from_native_reserve(self):
        # A tiny failure packet remains retainable on a volume below 15 GiB.
        with mock.patch.object(encrypt, "_free_bytes", return_value=128 * 1024**2):
            result = self.run_encrypt()
        self.assertTrue(result["encryption_passed"])
        self.assertEqual(encrypt.RETENTION_DISK_MARGIN_BYTES, 64 * 1024**2)

    def test_storage_below_retention_margin_starts_no_process(self):
        with mock.patch.object(encrypt, "_free_bytes", return_value=encrypt.RETENTION_DISK_MARGIN_BYTES - 1):
            with self.assertRaisesRegex(encrypt.EncryptionError, "disk-reserve"):
                self.run_encrypt()
        self.assertFalse(self.output.exists())
        self.assertFalse(self.private.exists())
        self.assertFalse(self.audit.exists())

    def test_exact_ciphertext_upper_bound_is_admitted_before_launch(self):
        observations = []
        original = encrypt._reserve
        def observed(fd, additional=0):
            observations.append(additional)
            original(fd, additional)
        with mock.patch.object(encrypt, "_reserve", side_effect=observed):
            self.run_encrypt()
        size = self.capture.stat().st_size
        bound = size + ((size + 65535) // 65536) * 16 + 4096
        self.assertIn(bound, observations)
        self.assertLessEqual((self.output / encrypt.CIPHERTEXT_NAME).stat().st_size, bound)

    def test_output_and_log_writes_recheck_space_and_fail_closed(self):
        original = encrypt._reserve
        def shortfall(fd, additional=0):
            if self.audit.exists() and additional:
                raise encrypt.EncryptionError("disk-reserve")
            return original(fd, additional)
        with mock.patch.object(encrypt, "_reserve", side_effect=shortfall):
            with self.assertRaisesRegex(encrypt.EncryptionError, "disk-reserve"):
                self.run_encrypt()
        self.assertFalse((self.output / encrypt.CIPHERTEXT_NAME).exists())
        self._assert_child_not_running()

    def test_tar_record_padding_long_utf8_pax_headers_and_age_chunk_boundaries(self):
        name = "/".join(["é" * 70, "nested", "opaque.bin"])
        for size in (0, 1, 65535, 65536, 65537, 131072):
            with self.subTest(size=size):
                self.put(name, b"z" * size)
                expected = self.source_bytes()
                self.run_encrypt()
                self.verify_captured_tar(expected)
                self.assertEqual(self.capture.stat().st_size % tarfile.RECORDSIZE, 0)
                self._remove_outputs()

    def test_empty_directory_still_has_a_manifest_and_root_directory(self):
        empty = self.root / "entirely-empty"
        empty.mkdir()
        result = self.run_encrypt(input_dir=empty)
        self.assertEqual(result["file_count"], 0)
        self.assertEqual(result["directory_count"], 1)
        self.verify_captured_tar({})

    def test_successful_cli_is_one_sanitized_json_record(self):
        result = subprocess.run([sys.executable, "-B", str(Path(encrypt.__file__).resolve()),
            "--input-dir", str(self.source), "--output-dir", str(self.output), "--recipient", RECIPIENT,
            "--age-binary", str(self.binary), "--expected-revision", REVISION],
            capture_output=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")
        value = json.loads(result.stdout)
        self.assertEqual(set(value), PUBLIC_FIELDS)
        self.assertTrue(value["encryption_passed"])
        self.assertNotIn(str(self.source).encode(), result.stdout)
        self.assertNotIn(RECIPIENT.encode(), result.stdout)

    def _pack_fixture(self):
        import test_p06_qualified_warm_pack as packaging_tests
        fixture = packaging_tests.PrivatePackagingTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_actual_complete_packaging_api_is_preserved_as_opaque_bytes(self):
        fixture = self._pack_fixture()
        receipt = fixture.success()
        self.assertTrue(receipt["complete_replay_original_created"])
        (fixture.output / ".extra-opaque-failure-log").write_bytes(self.secret)
        expected = self.source_bytes(fixture.output)
        self.run_encrypt(input_dir=fixture.output)
        self.verify_captured_tar(expected)

    def test_actual_partial_packaging_api_preserves_failed_records_exactly(self):
        fixture = self._pack_fixture()
        fixture.put("qualified-warm/report.json", b"unfinished\x00\xffPRIVATE_TOKEN")
        receipt = fixture.partial()
        self.assertTrue(receipt["partial_attempt"])
        expected = self.source_bytes(fixture.output)
        result = self.run_encrypt(input_dir=fixture.output)
        self.verify_captured_tar(expected)
        self.assertTrue(result["encryption_passed"])
        self.assertNotIn("complete_replay_original_created", result)

    def test_actual_packaging_failure_directory_preserves_partial_archive_and_receipt(self):
        import p06_qualified_warm_pack as packaging
        fixture = self._pack_fixture()
        def interrupted(path, members):
            with packaging._exclusive(path) as stream:
                stream.write(b"incomplete PRIVATE archive bytes\x00\xff")
            raise OSError("PRIVATE raw failure text")
        with mock.patch.object(packaging, "_write_zip", side_effect=interrupted):
            with self.assertRaises(OSError):
                fixture.success()
        expected = self.source_bytes(fixture.output)
        self.assertIn(packaging.FAILURE_NAME, expected)
        self.assertTrue(any(name.startswith("incomplete-") for name in expected))
        self.run_encrypt(input_dir=fixture.output)
        self.verify_captured_tar(expected)


if __name__ == "__main__":
    unittest.main()
