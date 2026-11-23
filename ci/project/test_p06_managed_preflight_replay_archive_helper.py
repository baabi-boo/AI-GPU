# SPDX-License-Identifier: Apache-2.0
"""Independent cache and source-pin controls for the managed archive helper."""

# ZIP's lazy filename codec must be ready before the file-loader guards.
import encodings.cp437
import hashlib
import importlib.machinery
import importlib.util
import marshal
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

import p06_managed_preflight_replay as reader
from p06_managed_preflight_replay_test_support import replay


class ManagedPreflightArchiveHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = reader.ROOT / reader.archive_helpers.ARCHIVE_READER_PATH
        cls.body = cls.source.read_bytes()
        if hashlib.sha256(cls.body).hexdigest() != reader.archive_helpers.ARCHIVE_READER_SHA256:
            raise AssertionError("current archive helper differs from its independent pin")

    def test_matching_timestamp_and_size_bytecode_is_not_executed(self):
        with tempfile.TemporaryDirectory(prefix="p06-archive-helper-cache-") as directory:
            root = Path(directory)
            source = root / reader.archive_helpers.ARCHIVE_READER_PATH
            source.parent.mkdir(parents=True)
            source.write_bytes(self.body)
            cache = Path(importlib.util.cache_from_source(str(source)))
            cache.parent.mkdir(parents=True)
            sentinel = "unverified cached archive helper"
            code = compile("CACHE_SENTINEL = " + repr(sentinel) + "\n", str(source), "exec")
            identity = source.stat()
            header = importlib.util.MAGIC_NUMBER + struct.pack(
                "<III", 0, int(identity.st_mtime) & 0xffffffff, identity.st_size & 0xffffffff)
            cache.write_bytes(header + marshal.dumps(code))

            spec = importlib.util.spec_from_file_location("p06_cache_control", source)
            ordinary = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(ordinary)
            self.assertEqual(ordinary.CACHE_SENTINEL, sentinel)
            self.assertFalse(hasattr(ordinary, "ArchiveReader"))
            self.assertEqual(source.read_bytes(), self.body)

            with mock.patch.object(reader, "ROOT", root), \
                 mock.patch.object(importlib.machinery.SourceFileLoader, "get_code",
                                   side_effect=AssertionError("unverified cached code requested")) as get_code, \
                 mock.patch.object(importlib.machinery.SourceFileLoader, "exec_module",
                                   side_effect=AssertionError("file loader executed")) as exec_module:
                api = reader._archive_api()
            get_code.assert_not_called()
            exec_module.assert_not_called()
            self.assertFalse(hasattr(api, "CACHE_SENTINEL"))
            self.assertEqual(api.__file__, str(source))
            self.assertEqual(api.__spec__.origin, str(source))
            self.assertTrue(callable(api.ArchiveReader))
            self.assertEqual(api.strict_json(b'{"value": 7}'), {"value": 7})
            with self.assertRaisesRegex(api.ArchiveError, "duplicate JSON field"):
                api.strict_json(b'{"value": 7, "value": 8}')

    def test_changed_current_source_rejects_before_compile_or_module_creation(self):
        with tempfile.TemporaryDirectory(prefix="p06-archive-helper-source-") as directory:
            root = Path(directory)
            source = root / reader.archive_helpers.ARCHIVE_READER_PATH
            source.parent.mkdir(parents=True)
            source.write_bytes(self.body + b"\nraise AssertionError('changed helper executed')\n")
            with mock.patch.object(reader, "ROOT", root), \
                 mock.patch("builtins.compile", side_effect=AssertionError("unverified source compiled")) as compiler, \
                 mock.patch.object(importlib.util, "spec_from_file_location",
                                   side_effect=AssertionError("unverified module created")) as spec:
                with self.assertRaisesRegex(reader.ReplayError, "trusted archive reader differs"):
                    reader._archive_api()
            compiler.assert_not_called()
            spec.assert_not_called()

    def test_original_complete_replay_bypasses_source_file_code_loaders(self):
        with mock.patch.object(importlib.machinery.SourceFileLoader, "get_code",
                               side_effect=AssertionError("cached code requested")) as get_code, \
             mock.patch.object(importlib.machinery.SourceFileLoader, "exec_module",
                               side_effect=AssertionError("file loader executed")) as exec_module:
            result = replay()
        get_code.assert_not_called()
        exec_module.assert_not_called()
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["counts"]["launches"], 132)
        self.assertEqual(result["counts"]["checked_words"], 4224)
        self.assertEqual(result["retained_source_files_checked"], 999)
        self.assertEqual(result["retained_payload_files_checked"], 17)
        self.assertEqual(result["native_execution"], "not_run")
        self.assertFalse(result["retained_code_executed"])
        for name in reader.contract_module.FALSE_CLAIMS:
            self.assertIs(result[name], False)


if __name__ == "__main__":
    unittest.main()
