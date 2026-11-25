# SPDX-License-Identifier: Apache-2.0
"""Offline close-error ownership and fixed-diagnostic regressions."""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
from unittest import mock

import p06_qualified_warm_retention as retention
import p06_qualified_warm_restore as restore


REVISION = "a9" * 20
PRIVATE_ERROR = "PRIVATE-CLOSE-ERROR"
INPUT_LABELS = ("summary.fd", "summary.parent", "archive.fd", "archive.parent")


def close_error():
    return OSError(errno.EIO, PRIVATE_ERROR, "/PRIVATE-CLOSE-PATH")


def descriptors():
    result = set()
    for name in os.listdir("/proc/self/fd"):
        try:
            os.fstat(int(name))
        except OSError:
            continue
        result.add(int(name))
    return result


class QualifiedWarmCleanupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-cleanup-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.archive = self.root / "archive.PRIVATE.tar"
        self.summary = self.root / "summary.json"
        self.payload = b"PRIVATE-OPAQUE-PAYLOAD\x00\xff"
        manifest = {"schema_version": 1, "contract_id": retention.RETENTION_CONTRACT_ID,
            "expected_revision": REVISION, "directories": [""],
            "files": [{"path": "payload", "size_bytes": len(self.payload),
                       "sha256": hashlib.sha256(self.payload).hexdigest()}]}
        raw = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
        with tarfile.open(self.archive, "w", format=tarfile.PAX_FORMAT) as archive:
            for name, body in (("manifest.json", raw), ("private", None),
                               ("private/payload", self.payload)):
                info = tarfile.TarInfo(name)
                info.type = tarfile.DIRTYPE if body is None else tarfile.REGTYPE
                info.mode = 0o700 if body is None else 0o600
                info.size = 0 if body is None else len(body)
                archive.addfile(info, None if body is None else io.BytesIO(body))
        self.digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.summary.write_text(json.dumps({"schema_version": 1,
            "contract_id": retention.RETENTION_CONTRACT_ID, "expected_revision": REVISION,
            "outcome": "pass", "encryption_passed": True, "file_count": 1,
            "directory_count": 1, "input_bytes": len(self.payload),
            "ciphertext_bytes": 1024, "ciphertext_sha256": "f" * 64}))

    def reader(self):
        return retention.RetentionArchive(self.archive, self.digest,
            expected_revision=REVISION, summary=self.summary)

    def run_restore(self, output):
        return restore.restore_archive(self.archive, self.digest,
            expected_revision=REVISION, summary=self.summary, output_dir=output)

    @contextmanager
    def no_fd_leaks(self):
        before = descriptors()
        try:
            yield
        finally:
            after = descriptors()
            for fd in after - before:
                os.close(fd)
            self.assertEqual(after, before)

    @contextmanager
    def faulty_closes(self, targets, failures):
        original = os.close
        attempted = []

        def close(fd):
            # Remove labels after the first attempt: later opens may reuse this fd.
            label = targets.pop(fd, None)
            if label is not None:
                attempted.append(label)
            original(fd)
            if label in failures:
                raise failures[label]

        with mock.patch.object(os, "close", side_effect=close):
            yield attempted

    def capture_inputs(self, retained, targets):
        sources = retained._summary, retained._archive
        for name, source in zip(("summary", "archive"), sources):
            if source is not None:
                targets[source.fd] = name + ".fd"
                targets[source.parent] = name + ".parent"
        return sources

    def assert_closed(self, retained, sources):
        self.assertIsNone(retained._summary)
        self.assertIsNone(retained._archive)
        self.assertFalse(retained._validated)
        for source in sources:
            self.assertIsNone(source.fd)
            self.assertIsNone(source.parent)
        retained.close()

    @contextmanager
    def restore_targets(self, output, targets):
        original = restore._mkdir

        def mkdir(parent_fd, name):
            result = original(parent_fd, name)
            if name == output.name:
                targets[result[0]], targets[parent_fd] = "root", "parent"
            return result

        with mock.patch.object(restore, "_mkdir", side_effect=mkdir):
            yield

    def assert_private_output(self, output):
        self.assertEqual((output / "private/payload").read_bytes(), self.payload)
        for path in (output, *output.rglob("*")):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode),
                             0o700 if path.is_dir() else 0o600)

    def test_reader_normal_completion_rejects_each_owned_close_error(self):
        original = retention.RetentionArchive.report
        for label in (*INPUT_LABELS, "all"):
            targets, captured = {}, []
            failures = {name: close_error() for name in INPUT_LABELS
                        if name == label or label == "all"}

            def report(retained):
                captured.append((retained, self.capture_inputs(retained, targets)))
                return original(retained)

            with self.subTest(label=label), self.no_fd_leaks(), \
                 self.faulty_closes(targets, failures) as attempted, \
                 mock.patch.object(retention.RetentionArchive, "report", report), \
                 self.assertRaises(retention.RetentionError) as caught:
                retention.inspect_archive(self.archive, self.digest,
                    expected_revision=REVISION, summary=self.summary)
            self.assertEqual(str(caught.exception), "retention-invalid")
            self.assertEqual(attempted, list(INPUT_LABELS))
            self.assert_closed(*captured[0])

    def test_reader_preserves_context_failure_while_closing_all_inputs(self):
        for primary in (retention.RetentionError("unknown-file"),
                        RuntimeError("primary"), KeyboardInterrupt("primary")):
            targets = {}
            with self.subTest(primary=type(primary).__name__), self.no_fd_leaks(), \
                 self.faulty_closes(targets, {name: close_error() for name in INPUT_LABELS}) as attempted, \
                 self.assertRaises(type(primary)) as caught:
                with self.reader() as retained:
                    sources = self.capture_inputs(retained, targets)
                    raise primary
            self.assertIs(caught.exception, primary)
            self.assertEqual(attempted, list(INPUT_LABELS))
            self.assert_closed(retained, sources)

    def test_reader_preserves_final_integrity_failure(self):
        targets = {}
        primary = retention.RetentionError("archive-changed")
        with self.no_fd_leaks(), \
             self.faulty_closes(targets, {name: close_error() for name in INPUT_LABELS}) as attempted, \
             mock.patch.object(retention.RetentionArchive, "assert_unchanged", side_effect=primary), \
             self.assertRaises(retention.RetentionError) as caught:
            with self.reader() as retained:
                sources = self.capture_inputs(retained, targets)
        self.assertIs(caught.exception, primary)
        self.assertEqual(attempted, list(INPUT_LABELS))
        self.assert_closed(retained, sources)

    def test_reader_preserves_summary_validation_failure(self):
        value = json.loads(self.summary.read_bytes())
        value["file_count"] = 2
        self.summary.write_text(json.dumps(value))
        targets, sources = {}, []
        original = retention._Input.__init__

        def initialize(source, path, kind, maximum):
            original(source, path, kind, maximum)
            targets[source.fd], targets[source.parent] = kind + ".fd", kind + ".parent"
            sources.append(source)

        retained = self.reader()
        with self.no_fd_leaks(), \
             self.faulty_closes(targets, {name: close_error() for name in INPUT_LABELS}) as attempted, \
             mock.patch.object(retention._Input, "__init__", initialize), \
             self.assertRaisesRegex(retention.RetentionError, "^summary-mismatch$"):
            retained.__enter__()
        self.assertEqual(attempted, list(INPUT_LABELS))
        self.assert_closed(retained, sources)

    def test_input_initialization_preserves_failure_and_closes_both_handles(self):
        for kind, path in (("archive", self.archive), ("summary", self.summary)):
            targets = {}
            primary = retention.RetentionError(kind + "-changed")

            def identity(source):
                targets[source.fd], targets[source.parent] = "fd", "parent"
                raise primary

            source = retention._Input.__new__(retention._Input)
            with self.subTest(kind=kind), self.no_fd_leaks(), \
                 self.faulty_closes(targets, {"fd": close_error(), "parent": close_error()}) as attempted, \
                 mock.patch.object(retention._Input, "assert_identity", identity), \
                 self.assertRaises(retention.RetentionError) as caught:
                source.__init__(path, kind, retention.MAX_ARCHIVE_BYTES)
            self.assertIs(caught.exception, primary)
            self.assertEqual(attempted, ["fd", "parent"])
            self.assertIsNone(source.fd)
            self.assertIsNone(source.parent)

    def test_input_identity_preserves_failure_when_probe_close_also_fails(self):
        with self.no_fd_leaks():
            source = retention._Input(self.archive, "archive", retention.MAX_ARCHIVE_BYTES)
            targets = {}
            original = retention._directory

            def directory(path):
                result = original(path)
                targets[result[0]] = "probe"
                return result

            source.identity = ()
            try:
                with self.faulty_closes(targets, {"probe": close_error()}) as attempted, \
                     mock.patch.object(retention, "_directory", side_effect=directory), \
                     self.assertRaisesRegex(retention.RetentionError, "^archive-changed$"):
                    source.assert_identity()
                self.assertEqual(attempted, ["probe"])
            finally:
                source.close()

    def test_input_close_never_retries_a_released_and_reused_descriptor(self):
        with self.no_fd_leaks():
            source = retention._Input(self.archive, "archive", retention.MAX_ARCHIVE_BYTES)
            target, parent = source.fd, source.parent
            original = os.close
            replacement, attempts = [], []

            def close(fd):
                attempts.append(fd)
                original(fd)
                if fd == target:
                    replacement.append(os.open("/dev/null", os.O_RDONLY))
                    self.assertEqual(replacement[0], target)
                    raise close_error()

            try:
                with mock.patch.object(os, "close", side_effect=close), \
                     self.assertRaises(retention.RetentionError):
                    source.close()
                source.close()
                os.fstat(replacement[0])
                self.assertEqual(attempts, [target, parent])
            finally:
                for fd in replacement:
                    original(fd)

    def test_restore_terminal_closes_are_fixed_errors_and_attempt_both_directories(self):
        cases = (({"root": close_error()}, "filesystem-failed"),
                 ({"parent": close_error()}, "filesystem-failed"),
                 ({"root": close_error(), "parent": RuntimeError(PRIVATE_ERROR)}, "filesystem-failed"),
                 ({"root": RuntimeError(PRIVATE_ERROR)}, "restore-failed"),
                 ({"root": KeyboardInterrupt(PRIVATE_ERROR)}, "interrupted"))
        for index, (failures, code) in enumerate(cases):
            output, targets = self.root / ("output-" + str(index)), {}
            with self.subTest(code=code, index=index), self.no_fd_leaks(), \
                 self.restore_targets(output, targets), \
                 self.faulty_closes(targets, failures) as attempted, \
                 self.assertRaises(restore.RestoreError) as caught:
                self.run_restore(output)
            self.assertEqual(str(caught.exception), code)
            self.assertEqual(attempted, ["root", "parent"])
            self.assert_private_output(output)
            self.assertFalse((output / restore.INCOMPLETE_NAME).exists())

    def test_restore_terminal_close_cli_is_failure_without_private_diagnostics(self):
        output, targets = self.root / "output", {}
        stdout, stderr = io.StringIO(), io.StringIO()
        with self.no_fd_leaks(), self.restore_targets(output, targets), \
             self.faulty_closes(targets, {"root": close_error()}) as attempted, \
             redirect_stdout(stdout), redirect_stderr(stderr):
            status = restore.main(["restore", "--archive", str(self.archive),
                "--sha256", self.digest, "--expected-revision", REVISION,
                "--summary", str(self.summary), "--output-dir", str(output)])
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(stdout.getvalue()), restore._failure_report("filesystem-failed"))
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn("PRIVATE", stdout.getvalue())
        self.assertEqual(attempted, ["root", "parent"])

    def test_restore_preserves_initial_failure_against_all_owned_close_errors(self):
        output, targets = self.root / "output", {}
        primary = restore.RestoreError("output-verification-failed")
        original = retention._Input.__init__

        def initialize(source, path, kind, maximum):
            original(source, path, kind, maximum)
            targets[source.fd], targets[source.parent] = kind + ".fd", kind + ".parent"

        with self.no_fd_leaks(), self.restore_targets(output, targets), \
             self.faulty_closes(targets, {name: close_error()
                 for name in (*INPUT_LABELS, "root", "parent")}) as attempted, \
             mock.patch.object(retention._Input, "__init__", initialize), \
             mock.patch.object(restore, "_verify_tree", side_effect=primary), \
             self.assertRaises(restore.RestoreError) as caught:
            self.run_restore(output)
        self.assertIs(caught.exception, primary)
        self.assertEqual(attempted, [*INPUT_LABELS, "root", "parent"])
        self.assert_private_output(output)
        self.assertEqual(json.loads((output / restore.INCOMPLETE_NAME).read_bytes())["outcome"],
                         "incomplete")

    def test_restore_reader_close_failure_retains_incomplete_output(self):
        output, targets = self.root / "output", {}
        original = retention.RetentionArchive.report

        def report(retained):
            self.capture_inputs(retained, targets)
            return original(retained)

        with self.no_fd_leaks(), self.restore_targets(output, targets), \
             self.faulty_closes(targets, {name: close_error() for name in INPUT_LABELS}) as attempted, \
             mock.patch.object(retention.RetentionArchive, "report", report), \
             self.assertRaisesRegex(restore.RestoreError, "^retention-rejected$"):
            self.run_restore(output)
        self.assertEqual(attempted, [*INPUT_LABELS, "root", "parent"])
        self.assert_private_output(output)
        self.assertEqual(json.loads((output / restore.INCOMPLETE_NAME).read_bytes())["outcome"],
                         "incomplete")

    def test_incomplete_marker_close_cannot_override_the_restore_failure(self):
        output, targets = self.root / "output", {}
        primary = restore.RestoreError("output-verification-failed")
        original_verify, original_open = restore._verify_tree, os.open
        verified = []

        def verify(*args):
            verified.append(True)
            if len(verified) == 2:
                raise primary
            return original_verify(*args)

        def open_file(path, *args, **kwargs):
            fd = original_open(path, *args, **kwargs)
            if path == restore.INCOMPLETE_NAME and len(verified) == 2:
                targets[fd] = "marker"
            return fd

        with self.no_fd_leaks(), self.restore_targets(output, targets), \
             self.faulty_closes(targets, {"marker": close_error()}) as attempted, \
             mock.patch.object(restore, "_verify_tree", side_effect=verify), \
             mock.patch.object(os, "open", side_effect=open_file), \
             self.assertRaises(restore.RestoreError) as caught:
            self.run_restore(output)
        self.assertIs(caught.exception, primary)
        self.assertEqual(attempted, ["marker", "root", "parent"])
        self.assert_private_output(output)
        self.assertEqual(json.loads((output / restore.INCOMPLETE_NAME).read_bytes())["outcome"],
                         "incomplete")

    def test_directory_handoffs_never_retry_a_released_and_reused_descriptor(self):
        child = self.root / "child"
        child.mkdir(mode=0o700)
        for kind in ("reader", "restore", "owned"):
            with self.subTest(kind=kind), self.no_fd_leaks():
                root_fd = os.open(self.root, restore._DIRECTORY_FLAGS)
                directories = {"": restore._identity(os.fstat(root_fd)),
                               "child": restore._identity(child.stat())}
                original = os.close
                replacement, attempts = [], []

                def close(fd):
                    attempts.append(fd)
                    original(fd)
                    if not replacement:
                        replacement.append(os.open("/dev/null", os.O_RDONLY))
                        self.assertEqual(replacement[0], fd)
                        raise close_error()

                try:
                    with mock.patch.object(os, "close", side_effect=close), \
                         self.assertRaises((retention.RetentionError, restore.RestoreError)):
                        if kind == "reader":
                            retention._directory(child)
                        elif kind == "restore":
                            restore._open_directory(child)
                        else:
                            restore._open_owned_directory(root_fd, directories, "child")
                    self.assertEqual(len(attempts), 2)
                    self.assertNotEqual(*attempts)
                    os.fstat(replacement[0])
                finally:
                    for fd in replacement:
                        original(fd)
                    original(root_fd)

    def test_new_file_closes_both_handles_and_preserves_initial_failure(self):
        for fail_writer in (False, True):
            with self.subTest(fail_writer=fail_writer), self.no_fd_leaks():
                root_fd = os.open(self.root, restore._DIRECTORY_FLAGS)
                directories = {"": restore._identity(os.fstat(root_fd))}
                primary = restore.RestoreError("short-output-write")
                targets = {}
                original = restore._open_owned_directory

                def directory(*args):
                    fd = original(*args)
                    targets[fd] = "parent"
                    return fd

                def writer(fd):
                    targets[fd] = "file"
                    if fail_writer:
                        raise primary
                    restore._write_all(fd, self.payload)

                try:
                    with self.faulty_closes(targets, {"file": close_error(),
                            "parent": RuntimeError(PRIVATE_ERROR)}) as attempted, \
                         mock.patch.object(restore, "_open_owned_directory", side_effect=directory), \
                         self.assertRaises(restore.RestoreError) as caught:
                        restore._new_file(root_fd, directories, "new-" + str(fail_writer),
                            len(self.payload), hashlib.sha256(self.payload).hexdigest(), writer)
                    if fail_writer:
                        self.assertIs(caught.exception, primary)
                    else:
                        self.assertEqual(str(caught.exception), "filesystem-failed")
                    self.assertEqual(attempted, ["file", "parent"])
                finally:
                    os.close(root_fd)

    def test_directory_initial_stat_failure_still_closes_the_root_handle(self):
        primary = OSError(errno.EIO, "initial failure")
        with self.no_fd_leaks(), mock.patch.object(os, "fstat", side_effect=primary), \
             self.assertRaises(OSError) as caught:
            restore._open_directory(self.root)
        self.assertIs(caught.exception, primary)


if __name__ == "__main__":
    unittest.main()
