# SPDX-License-Identifier: Apache-2.0
"""Independent import-boundary checks for the trusted configuration renderer."""

import importlib.machinery
import importlib.util
import marshal
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

import p06_managed_preflight_generated as generated
from p06_managed_preflight_replay_test_support import Packet, PREFIX
from p06_replay import ReplayError


class ManagedPreflightGeneratedSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with Packet() as packet:
            cls.sources = {name: packet[PREFIX + "artifacts/source/" + name]
                           for name in generated.INPUT_SHA256}
            cls.headers = {name: packet[PREFIX + "artifacts/simx-fp16/frozen/" + name]
                           for name in generated.HEADERS}

    def trusted_tree(self, root):
        for name, body in self.sources.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)

    def test_matching_timestamp_bytecode_is_not_loaded(self):
        original_renderer = generated.TRUSTED_GENERATOR_MODULE
        with tempfile.TemporaryDirectory(prefix="p06-renderer-bytecode-") as directory:
            root = Path(directory)
            self.trusted_tree(root)
            source = root / generated.GENERATOR_PATH
            cache = Path(importlib.util.cache_from_source(str(source)))
            cache.parent.mkdir(parents=True, exist_ok=True)
            marker = "untrusted cached renderer executed"
            code = compile("raise AssertionError(" + repr(marker) + ")\n", str(source), "exec")
            identity = source.stat()
            header = importlib.util.MAGIC_NUMBER + struct.pack(
                "<III", 0, int(identity.st_mtime) & 0xffffffff, identity.st_size & 0xffffffff)
            cache.write_bytes(header + marshal.dumps(code))
            loader = importlib.machinery.SourceFileLoader(generated.GENERATOR_MODULE_NAME, str(source))
            self.assertIn(marker, loader.get_code(generated.GENERATOR_MODULE_NAME).co_consts)

            with mock.patch.object(generated, "ROOT", root), mock.patch.dict(sys.modules), \
                    mock.patch.object(importlib.machinery.SourceFileLoader, "get_code",
                                      side_effect=AssertionError("cached code loader consulted")), \
                    mock.patch.object(importlib.machinery.SourceFileLoader, "exec_module",
                                      side_effect=AssertionError("file loader executed")):
                renderer = generated._load_renderer()
                with mock.patch.object(generated, "TRUSTED_GENERATOR_MODULE", renderer):
                    receipt = generated.validate_generated_headers(
                        source_body=self.sources.__getitem__, build_body=self.headers.__getitem__)
                    self.assertEqual(len(receipt["headers"]), 4)
                    self.assertFalse(receipt["retained_code_executed"])
                    self.assertEqual(receipt["native_execution"], "not_run")
            self.assertIs(generated.TRUSTED_GENERATOR_MODULE, original_renderer)
            self.assertIs(sys.modules[generated.GENERATOR_MODULE_NAME], original_renderer)

    def test_changed_current_generator_rejects_before_bootstrap_compiles_it(self):
        name = "p06_generated_security_bootstrap"
        current = generated.ROOT / "ci/project/p06_managed_preflight_generated.py"
        bootstrap = compile(current.read_bytes(), str(current), "exec")
        with tempfile.TemporaryDirectory(prefix="p06-renderer-bootstrap-") as directory:
            root = Path(directory)
            self.trusted_tree(root)
            (root / generated.GENERATOR_PATH).write_text(
                "raise AssertionError('modified generator executed')\n", encoding="utf-8")
            namespace = {"__name__": name,
                         "__file__": str(root / "ci/project/p06_managed_preflight_generated.py")}
            with mock.patch("builtins.compile", side_effect=AssertionError("unverified source compiled")), \
                    mock.patch.object(importlib.util, "spec_from_file_location",
                                      side_effect=AssertionError("unverified renderer loader reached")):
                with self.assertRaisesRegex(ReplayError, "trusted generated input ci/gen_config.py"):
                    exec(bootstrap, namespace)


if __name__ == "__main__":
    unittest.main()
