# SPDX-License-Identifier: Apache-2.0
"""Synthetic vendor-input filesystem checks; no vendor software is executed."""

import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import hwemu_io


class HwEmuInputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="hwemu-io-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def file(self, name="input.bin", contents=b"synthetic input"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return {"path": str(path), "size_bytes": len(contents),
                "sha256": hashlib.sha256(contents).hexdigest()}

    def inputs(self, **kwargs):
        return self.enterContext(hwemu_io.Inputs(**kwargs))

    def test_hashes_exact_bytes_and_preserves_file(self):
        contents = bytes(range(256)) * 300 + b"tail"
        identity = self.file(contents=contents)
        inputs = self.inputs()
        self.assertEqual(inputs.check_file(identity, "xclbin"), identity)
        self.assertEqual(inputs.inventory(), [identity])
        inputs.recheck()
        self.assertEqual(Path(identity["path"]).read_bytes(), contents)

    def test_hash_path_does_not_buffer_blob(self):
        identity = self.file(contents=b"x" * 131073)
        with mock.patch.object(hwemu_io.PacketReader, "read_bytes",
                               side_effect=AssertionError("blob buffered")):
            self.assertEqual(self.inputs().check_file(identity), identity)

    def test_repeated_identity_consumes_budget_only_once(self):
        identity = self.file(contents=b"four")
        inputs = self.inputs(max_total_bytes=4, max_files=1)
        self.assertEqual(inputs.check_file(identity), identity)
        self.assertEqual(inputs.check_file(identity), identity)
        self.assertEqual(inputs.read_text(identity["path"]), "four")
        inputs.recheck()

    def test_independent_files_share_total_budget(self):
        first = self.file("one", b"123")
        second = self.file("two", b"456")
        inputs = self.inputs(max_total_bytes=5)
        inputs.check_file(first)
        with self.assertRaises(hwemu_io.InputError):
            inputs.check_file(second)

    def test_independent_files_share_file_budget(self):
        first = self.file("one", b"1")
        second = self.file("two", b"2")
        inputs = self.inputs(max_files=1)
        inputs.check_file(first)
        with self.assertRaises(hwemu_io.InputError):
            inputs.check_file(second)

    def test_zero_length_identity_is_valid(self):
        identity = self.file(contents=b"")
        self.assertEqual(self.inputs().check_file(identity), identity)

    def test_rejects_hash_and_size_mismatch(self):
        identity = self.file()
        for update in ({"sha256": "0" * 64},
                       {"size_bytes": identity["size_bytes"] - 1},
                       {"size_bytes": identity["size_bytes"] + 1}):
            with self.subTest(update=update), self.assertRaises(hwemu_io.InputError):
                self.inputs().check_file(dict(identity, **update))

    def test_rejects_invalid_identity_shape_and_values(self):
        identity = self.file()
        invalid = [None, [], {}, dict(identity, extra=1)]
        invalid.extend(dict(identity, size_bytes=value) for value in
                       (True, False, -1, 1.5, "1", 513 * 1024 * 1024))
        invalid.extend(dict(identity, sha256=value) for value in
                       (None, "", "A" * 64, "f" * 63, "z" * 64))
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(hwemu_io.InputError):
                self.inputs().check_file(value)

    def test_rejects_unsafe_noncanonical_paths(self):
        identity = self.file()
        paths = ("", "/", "relative", "//tmp/file", "/tmp/./file",
                 "/tmp/../file", "/tmp//file", "/tmp/file/", "/tmp/a b",
                 "/tmp/$(echo)", "/tmp/`echo`", "/tmp/a;b", "/tmp/a#b",
                 "/tmp/a:b", "/tmp/a\\b", "/tmp/a\n", "/tmp/é",
                 "/tmp/" + "a" * 256, "/" + "/".join(["a"] * 129),
                 None, Path(identity["path"]))
        inputs = self.inputs()
        for path in paths:
            with self.subTest(path=repr(path)), self.assertRaises(hwemu_io.InputError):
                inputs.check_file(dict(identity, path=path))
        self.assertEqual(inputs.inventory(), [])

    def test_rejects_leaf_and_ancestor_symlinks(self):
        identity = self.file("real/input")
        leaf = self.root / "leaf"
        leaf.symlink_to(identity["path"])
        ancestor = self.root / "alias"
        ancestor.symlink_to(self.root / "real", target_is_directory=True)
        for path in (leaf, ancestor / "input"):
            with self.subTest(path=path), self.assertRaises(hwemu_io.InputError):
                self.inputs().check_file(dict(identity, path=str(path)))

    def test_rejects_fifo_directory_and_missing_file(self):
        fifo = self.root / "pipe"
        os.mkfifo(fifo)
        for path in (fifo, self.root, self.root / "missing"):
            with self.subTest(path=path), self.assertRaises(hwemu_io.InputError):
                self.inputs().check_file({"path": str(path), "size_bytes": 0,
                                          "sha256": hashlib.sha256(b"").hexdigest()})

    def test_rejects_sparse_oversize_file_before_read(self):
        identity = self.file(contents=b"")
        with Path(identity["path"]).open("wb") as stream:
            stream.truncate(513 * 1024 * 1024)
        with mock.patch("baseline_packet_io.os.read",
                        side_effect=AssertionError("oversize read")):
            with self.assertRaises(hwemu_io.InputError):
                self.inputs().check_file(identity)

    def test_detects_input_mutation_and_replacement_on_recheck(self):
        for replacement in (False, True):
            identity = self.file()
            inputs = self.inputs()
            inputs.check_file(identity)
            path = Path(identity["path"])
            if replacement:
                path.unlink()
            path.write_bytes(b"changed")
            with self.subTest(replacement=replacement), self.assertRaises(hwemu_io.InputError):
                inputs.recheck()

    def test_read_json_rejects_ambiguous_and_nonfinite_values(self):
        for contents in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}',
                         b"[]", b"{}{}", b"\xff", b'{"a":' + b"[" * 65 + b"0" + b"]" * 65 + b"}"):
            identity = self.file(contents=contents)
            with self.subTest(contents=contents), self.assertRaises(hwemu_io.InputError):
                self.inputs().read_json(identity["path"])

    def test_read_text_utf8_and_json_are_bounded(self):
        text = self.file("text", b"abc")
        document = self.file("document", b'{"a":1}')
        inputs = self.inputs()
        self.assertEqual(inputs.read_text(text["path"]), "abc")
        self.assertEqual(inputs.read_json(document["path"]), {"a": 1})
        with self.assertRaises(hwemu_io.InputError):
            self.inputs().read_text(text["path"], limit=2)
        with self.assertRaises(hwemu_io.InputError):
            self.inputs().read_json(document["path"], limit=6)
        invalid = self.file("invalid", b"\xff")
        with self.assertRaises(hwemu_io.InputError):
            self.inputs().read_text(invalid["path"])

    def test_manifest_read_never_executes_or_writes_input(self):
        identity = self.file("manifest.json", b'{"command":"touch /tmp/must-not-run"}')
        before = Path(identity["path"]).stat()
        with mock.patch.object(subprocess, "Popen", side_effect=AssertionError("execution")), \
                mock.patch.object(os, "system", side_effect=AssertionError("shell")):
            result = hwemu_io.read_manifest(identity["path"])
        self.assertEqual(result, {"command": "touch /tmp/must-not-run"})
        after = Path(identity["path"]).stat()
        self.assertEqual((before.st_size, before.st_mtime_ns), (after.st_size, after.st_mtime_ns))

    def test_manifest_rejects_over_budget_input(self):
        identity = self.file(contents=b" " * hwemu_io.MAX_JSON_BYTES + b"{}")
        with self.assertRaises(hwemu_io.InputError):
            hwemu_io.read_manifest(identity["path"])

    def test_rejects_invalid_budgets_and_limits(self):
        for value in (True, False, 0, -1, 1.5, float("nan"), "1"):
            with self.subTest(value=value):
                with self.assertRaises(hwemu_io.InputError):
                    hwemu_io.Inputs(max_total_bytes=value)
                with self.assertRaises(hwemu_io.InputError):
                    hwemu_io.Inputs(max_files=value)
                with self.assertRaises(hwemu_io.InputError):
                    self.inputs().read_text("/tmp/unused", limit=value)
                with self.assertRaises(hwemu_io.InputError):
                    self.inputs().read_json("/tmp/unused", limit=value)
        with self.assertRaises(hwemu_io.InputError):
            hwemu_io.Inputs(max_files=65)
        with self.assertRaises(hwemu_io.InputError):
            hwemu_io.Inputs(max_total_bytes=hwemu_io.MAX_TOTAL_BYTES + 1)
        with self.assertRaises(hwemu_io.InputError):
            self.inputs().read_text("/tmp/unused", limit=hwemu_io.MAX_TEXT_BYTES + 1)
        with self.assertRaises(hwemu_io.InputError):
            self.inputs().read_json("/tmp/unused", limit=hwemu_io.MAX_JSON_BYTES + 1)

    def test_errors_do_not_echo_absolute_input_paths(self):
        identity = {"path": str(self.root / "private-name"), "size_bytes": 1,
                    "sha256": "0" * 64}
        with self.assertRaises(hwemu_io.InputError) as caught:
            self.inputs().check_file(identity, "xclbin")
        self.assertNotIn(str(self.root), str(caught.exception))
        self.assertNotIn("private-name", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
