# SPDX-License-Identifier: Apache-2.0
"""Real-file fault checks for atomic JSON checkpoint publication."""

import builtins
from contextlib import contextmanager, ExitStack
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import p02_matrix as matrix


class _FaultingStream:
    def __init__(self, stream, stage, fail):
        self.stream, self.stage, self.fail = stream, stage, fail

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def write(self, body):
        if self.stage == "write":
            self.stream.write(body[:len(body) // 2])
            self.stream.flush()
            self.fail()
        return self.stream.write(body)

    def flush(self):
        self.stream.flush()
        if self.stage == "flush":
            self.fail()


@contextmanager
def _fault_at(temporary, stage, error):
    failures, streams = [], []
    real_fsync, real_replace = os.fsync, os.replace

    def fail():
        failures.append(temporary.read_bytes())
        raise error

    def owns(descriptor):
        return os.path.samestat(os.fstat(descriptor), temporary.stat())

    def wrap_open(open_file):
        def open_stream(*args, **kwargs):
            stream = open_file(*args, **kwargs)
            if stream.writable() and temporary.exists() and owns(stream.fileno()):
                streams.append(stream)
                return _FaultingStream(stream, stage, fail)
            return stream
        return open_stream

    def fsync(descriptor, *args, **kwargs):
        if stage == "fsync" and owns(descriptor):
            fail()
        return real_fsync(descriptor, *args, **kwargs)

    def replace(source, destination, *args, **kwargs):
        if stage == "replace" and Path(source).name == temporary.name:
            fail()
        return real_replace(source, destination, *args, **kwargs)

    with ExitStack() as stack:
        # Both path-based open and fdopen reach these binary stream boundaries.
        for owner in (builtins, io):
            stack.enter_context(mock.patch.object(owner, "open", wrap_open(owner.open)))
        stack.enter_context(mock.patch.object(os, "fsync", fsync))
        stack.enter_context(mock.patch.object(os, "replace", replace))
        yield failures, streams


@contextmanager
def _forbid_file_open():
    with ExitStack() as stack:
        for owner in (builtins, io, os):
            stack.enter_context(mock.patch.object(
                owner, "open", side_effect=AssertionError("opened before validation")))
        yield


class CheckpointWriteFailureTests(unittest.TestCase):
    def test_io_faults_preserve_final_and_allow_a_later_explicit_write(self):
        value = {"state": "failed", "finished": True}
        expected = b'{\n  "finished": true,\n  "state": "failed"\n}\n'
        previous = b'{"state":"previous"}\n'
        for stage in ("write", "flush", "fsync", "replace"):
            for error_type in (OSError, KeyboardInterrupt):
                for existing in (False, True):
                    with self.subTest(stage=stage, error=error_type.__name__, existing=existing):
                        with tempfile.TemporaryDirectory(prefix="checkpoint-fault-") as directory:
                            path = Path(directory) / "report.json"
                            temporary = path.with_name(path.name + ".tmp")
                            if existing:
                                path.write_bytes(previous)
                            error = error_type("injected " + stage + " failure")
                            with _fault_at(temporary, stage, error) as (failures, streams):
                                with self.assertRaises(error_type) as caught:
                                    matrix._write_json(path, value)
                            self.assertIs(caught.exception, error)
                            self.assertEqual(len(failures), 1, "checkpoint retried implicitly")
                            self.assertTrue(streams)
                            self.assertTrue(all(stream.closed for stream in streams))
                            if stage == "write":
                                self.assertEqual(failures, [expected[:len(expected) // 2]])
                            else:
                                self.assertEqual(failures, [expected])
                            self.assertEqual(path.exists(), existing)
                            if existing:
                                self.assertEqual(path.read_bytes(), previous)
                            self.assertFalse(os.path.lexists(temporary))
                            matrix._write_json(path, value)
                            self.assertEqual(path.read_bytes(), expected)
                            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_serialization_errors_happen_before_file_io(self):
        circular = []
        circular.append(circular)
        cases = ((object(), TypeError), (float("nan"), ValueError),
                 (float("inf"), ValueError), (-float("inf"), ValueError),
                 (circular, ValueError))
        for index, (value, error_type) in enumerate(cases):
            with self.subTest(case=index):
                with tempfile.TemporaryDirectory(prefix="checkpoint-json-") as directory:
                    path = Path(directory) / "report.json"
                    path.write_bytes(b"previous\n")
                    with _forbid_file_open(), self.assertRaises(error_type):
                        matrix._write_json(path, value)
                    self.assertEqual(path.read_bytes(), b"previous\n")
                    self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_deterministic_encoding_and_exact_sixteen_mib_limit(self):
        with tempfile.TemporaryDirectory(prefix="checkpoint-limit-") as directory:
            path = Path(directory) / "report.json"
            expected = b'{\n  "a": "caf\\u00e9",\n  "z": [\n    true,\n    null\n  ]\n}\n'
            for value in ({"z": [True, None], "a": "caf\u00e9"},
                          {"a": "caf\u00e9", "z": [True, None]}):
                with self.subTest(keys=list(value)):
                    matrix._write_json(path, value)
                    self.assertEqual(path.read_bytes(), expected)
            limit = 16 * 1024 * 1024
            matrix._write_json(path, "x" * (limit - 3))
            self.assertEqual(path.stat().st_size, limit)
            with path.open("rb") as stream:
                self.assertEqual(stream.read(2), b'"x')
                stream.seek(-2, os.SEEK_END)
                self.assertEqual(stream.read(), b'"\n')
            path.write_bytes(b"previous\n")
            with _forbid_file_open(), self.assertRaisesRegex(ValueError, "16 MiB"):
                matrix._write_json(path, "x" * (limit - 2))
            self.assertEqual(path.read_bytes(), b"previous\n")
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_preexisting_temporary_entries_are_preserved(self):
        for kind in ("regular", "symlink", "dangling", "directory"):
            with self.subTest(kind=kind):
                with tempfile.TemporaryDirectory(prefix="checkpoint-owned-") as directory:
                    base = Path(directory)
                    path, temporary, foreign = (base / name for name in
                                                ("report.json", "report.json.tmp", "foreign"))
                    path.write_bytes(b"previous\n")
                    foreign.write_bytes(b"foreign\n")
                    if kind == "regular":
                        temporary.write_bytes(b"reserved\n")
                    elif kind == "directory":
                        temporary.mkdir()
                    else:
                        temporary.symlink_to(foreign if kind == "symlink" else base / "absent")
                    before = temporary.lstat()
                    with self.assertRaises(FileExistsError):
                        matrix._write_json(path, {"state": "new"})
                    self.assertTrue(os.path.samestat(temporary.lstat(), before))
                    self.assertEqual(path.read_bytes(), b"previous\n")
                    self.assertEqual(foreign.read_bytes(), b"foreign\n")
                    if kind == "regular":
                        self.assertEqual(temporary.read_bytes(), b"reserved\n")
                    elif kind == "directory":
                        self.assertEqual(list(temporary.iterdir()), [])
                    else:
                        self.assertEqual(os.readlink(temporary),
                                         str(foreign if kind == "symlink" else base / "absent"))
                    self.assertEqual(set(base.iterdir()), {path, temporary, foreign})


if __name__ == "__main__":
    unittest.main()
