# SPDX-License-Identifier: Apache-2.0
"""Synthetic external source expectations; no native or Git-provenance claim."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import p06_managed_preflight_sources as inventory


REVISION = "1234567890abcdef1234567890abcdef12345678"


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def descriptor(name, body=b"synthetic source body\n"):
    return {"path": name, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}


def manifest():
    return {"schema_version": 1, "contract_id": inventory.CONTRACT_ID,
            "producer_contract_id": inventory.PRODUCER_CONTRACT_ID,
            "source_revision": REVISION,
            "sources": [descriptor(name) for name in inventory.REQUIRED_SOURCE_NAMES]}


class ManagedPreflightSourceTests(unittest.TestCase):
    def setUp(self):
        self.document = manifest()

    def validate(self, document=None):
        return inventory.validate_source_inventory(
            self.document if document is None else document, expected_revision=REVISION)

    def decode(self, contents, expected_sha256=None):
        return inventory.decode_source_inventory(contents, expected_revision=REVISION,
            expected_sha256=hashlib.sha256(contents).hexdigest() if expected_sha256 is None
            else expected_sha256)

    def add(self, name):
        self.document["sources"].append(descriptor(name))
        self.document["sources"].sort(key=lambda row: row["path"])

    def test_complete_minimum_is_frozen_and_copied(self):
        names = inventory.required_source_names()
        self.assertEqual(len(names), 806)
        self.assertEqual(hashlib.sha256("".join(name + "\n" for name in names).encode()).hexdigest(),
                         "29d404d27008fa1e83f3110541782a9f641f2d426602cac096477f7f383f4f1a")
        result = self.validate()
        self.assertEqual(result, self.document)
        result["sources"][0]["sha256"] = "0" * 64
        self.assertNotEqual(result, self.document)

    def test_required_uncompiled_headers_helpers_and_workflows_cannot_disappear(self):
        required = ("sim/simx/processor_impl.h", "hw/rtl/core/VX_core.sv",
                    "ci/project/baseline_packet_io.py", "sw/runtime/common/vortex2_internal.h",
                    "tests/regression/ai_counter_preflight/hooks.cpp",
                    ".github/workflows/p06-managed-preflight.yml")
        for name in required:
            with self.subTest(name=name):
                changed = manifest()
                self.assertIn(name, [row["path"] for row in changed["sources"]])
                changed["sources"] = [row for row in changed["sources"] if row["path"] != name]
                with self.assertRaises(inventory.SourceInventoryError):
                    self.validate(changed)

    def test_populated_dependency_headers_and_new_source_extensions_require_exact_matching(self):
        for name in ("third_party/ramulator/src/controller/controller.h",
                     "third_party/ramulator/ext/yaml-cpp/include/yaml-cpp/node/node.h",
                     "third_party/softfloat/source/RISCV/specialize.h",
                     "ci/project/p06_managed_preflight_replay.py",
                     "tests/regression/ai_counter_preflight/additional.h"):
            self.add(name)
        expected = self.validate()
        actual = deepcopy(expected["sources"])
        self.assertEqual(inventory.validate_retained_sources(actual, expected,
                         expected_revision=REVISION), actual)
        actual.pop()
        with self.assertRaises(inventory.SourceInventoryError):
            inventory.validate_retained_sources(actual, expected, expected_revision=REVISION)

    def test_arbitrary_roots_evidence_binaries_and_hidden_extensions_reject(self):
        for name in ("etc/passwd", "docs/project/evidence/new.py", "ci/project/evidence/new.py",
                     "sim/simx/.hidden/new.h", "ci/project/new.zip", "sw/runtime/libvortex.so",
                     "third_party/arbitrary/header.h", ".github/workflows/new.yml",
                     "docs/designs/new.md", "tests/unrelated/new.cpp"):
            with self.subTest(name=name):
                self.document = manifest()
                self.add(name)
                with self.assertRaises(inventory.SourceInventoryError):
                    self.validate()

    def test_path_traversal_absolute_windows_control_and_unicode_reject(self):
        for name in ("../x", "/tmp/x", "ci/project/../escape.py", "ci//project/x.py",
                     "ci/project/./x.py", "ci\\project\\x.py", "C:/x.py",
                     "ci/project/x\n.py", "ci/project/x\x00.py", "ci/project/café.py",
                     "ci/project/$(id).py", "ci/project/.git/config"):
            with self.subTest(name=name):
                self.document = manifest()
                self.add(name)
                with self.assertRaises(inventory.SourceInventoryError):
                    self.validate()

    def test_path_length_depth_component_and_type_bounds(self):
        for name in ("ci/project/" + "a" * 256 + ".py",
                     "ci/project/" + "a/" * 65 + "x.py",
                     "ci/project/" + "a" * 4096 + ".py", 1, None, True):
            with self.subTest(name=name):
                self.document = manifest()
                self.document["sources"][0]["path"] = name
                with self.assertRaises(inventory.SourceInventoryError):
                    self.validate()

    def test_duplicate_and_unsorted_descriptors_reject(self):
        for changed in (self.document["sources"] + [self.document["sources"][-1]],
                        list(reversed(self.document["sources"]))):
            self.document["sources"] = changed
            with self.assertRaises(inventory.SourceInventoryError):
                self.validate()

    def test_descriptor_fields_are_exact(self):
        for operation in (lambda row: row.update(extra=1), lambda row: row.pop("sha256")):
            self.document = manifest()
            operation(self.document["sources"][0])
            with self.assertRaises(inventory.SourceInventoryError):
                self.validate()

    def test_descriptor_digest_is_lowercase_sha256_text(self):
        for value in ("A" * 64, "a" * 63, "a" * 65, "g" * 64, "a" * 64 + "\n", True, None):
            self.document = manifest()
            self.document["sources"][0]["sha256"] = value
            with self.subTest(value=value), self.assertRaises(inventory.SourceInventoryError):
                self.validate()

    def test_descriptor_sizes_are_bounded_integers_not_booleans_or_floats(self):
        for value in (-1, 256 * 1024**2 + 1, True, False, 1.0, "1", None):
            self.document = manifest()
            self.document["sources"][0]["size_bytes"] = value
            with self.subTest(value=value), self.assertRaises(inventory.SourceInventoryError):
                self.validate()
        for value in (0, 256 * 1024**2):
            self.document = manifest()
            self.document["sources"][0]["size_bytes"] = value
            self.assertEqual(self.validate()["sources"][0]["size_bytes"], value)

    def test_source_inventory_count_and_container_bounds(self):
        for rows in ([], None, {}, tuple(self.document["sources"]),
                     [self.document["sources"][0]] * 20001):
            self.document["sources"] = rows
            with self.assertRaises(inventory.SourceInventoryError):
                self.validate()

    def test_manifest_fields_are_exact(self):
        for key in tuple(self.document):
            changed = manifest()
            del changed[key]
            with self.subTest(missing=key), self.assertRaises(inventory.SourceInventoryError):
                self.validate(changed)
        self.document["qualified"] = False
        with self.assertRaises(inventory.SourceInventoryError):
            self.validate()

    def test_version_and_contract_types_are_exact(self):
        for key, values in (("schema_version", (True, 1.0, "1", 2)),
                            ("contract_id", (None, 1, "simx-counter-source-inventory-v1")),
                            ("producer_contract_id", (None, 1, "simx-counter-public-native-v1"))):
            for value in values:
                changed = manifest()
                changed[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(inventory.SourceInventoryError):
                    self.validate(changed)

    def test_expected_revision_is_full_lowercase_and_must_match(self):
        for value in (None, True, "A" * 40, "a" * 39, "a" * 41, "a" * 40 + "\n", "0" * 40):
            with self.subTest(value=value), self.assertRaises(inventory.SourceInventoryError):
                inventory.validate_source_inventory(self.document, expected_revision=value)

    def test_manifest_revision_cannot_supply_its_own_trust_anchor(self):
        self.document["source_revision"] = "0" * 40
        with self.assertRaises(inventory.SourceInventoryError):
            self.validate()

    def test_decode_checks_exact_original_bytes(self):
        body = encoded(self.document)
        self.assertEqual(self.decode(body), self.document)
        with self.assertRaises(inventory.SourceInventoryError):
            self.decode(body + b" ", hashlib.sha256(body).hexdigest())

    def test_digest_expectations_reject_before_any_file_access(self):
        for value in (None, True, "A" * 64, "a" * 63, "g" * 64, "a" * 64 + "\n"):
            with self.subTest(value=value), mock.patch.object(inventory, "PacketReader") as reader:
                with self.assertRaises(inventory.SourceInventoryError):
                    inventory.load_source_inventory("/unavailable/manifest.json", expected_sha256=value,
                                                    expected_revision=REVISION)
                reader.assert_not_called()

    def test_decode_does_not_parse_digest_mismatches(self):
        with mock.patch.object(inventory, "load_json_bytes") as parser:
            with self.assertRaises(inventory.SourceInventoryError):
                self.decode(encoded(self.document), "0" * 64)
            parser.assert_not_called()

    def test_duplicate_json_fields_reject(self):
        body = encoded(self.document).replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1')
        with self.assertRaises(inventory.SourceInventoryError):
            self.decode(body)

    def test_nonfinite_invalid_utf8_and_nonobject_json_reject(self):
        for body in (b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}', b'\xff', b'[]', b'null'):
            with self.subTest(body=body), self.assertRaises(inventory.SourceInventoryError):
                self.decode(body)

    def test_json_depth_and_token_limits_reject(self):
        for body in (b'{"x":' + b'[' * 65 + b'0' + b']' * 65 + b'}',
                     b'{"x":[' + b'0,' * 250001 + b'0]}'):
            with self.assertRaises(inventory.SourceInventoryError):
                self.decode(body)

    def test_empty_oversized_and_mutable_byte_inputs_reject(self):
        with mock.patch.object(inventory, "MAX_MANIFEST_BYTES", 32):
            for body in (b'', b' ' * 33, bytearray(b'{}')):
                with self.subTest(size=len(body)), self.assertRaises(inventory.SourceInventoryError):
                    inventory.decode_source_inventory(body, expected_revision=REVISION,
                        expected_sha256=hashlib.sha256(body).hexdigest())

    def test_retained_digest_or_size_substitution_rejects(self):
        expected = self.validate()
        for key, value in (("sha256", "0" * 64), ("size_bytes", 1)):
            actual = deepcopy(expected["sources"])
            actual[-1][key] = value
            with self.subTest(key=key), self.assertRaises(inventory.SourceInventoryError):
                inventory.validate_retained_sources(actual, expected, expected_revision=REVISION)

    def test_retained_unexpected_allowed_source_rejects(self):
        actual = deepcopy(self.document["sources"])
        actual.append(descriptor("ci/project/extra.py"))
        actual.sort(key=lambda row: row["path"])
        with self.assertRaises(inventory.SourceInventoryError):
            inventory.validate_retained_sources(actual, self.document, expected_revision=REVISION)

    def test_descriptor_validation_performs_no_io_or_execution(self):
        self.add("ci/project/replay_extension.py")
        with mock.patch("builtins.open", side_effect=AssertionError("source file opened")), \
             mock.patch.object(Path, "open", side_effect=AssertionError("source file opened")), \
             mock.patch.object(Path, "resolve", side_effect=AssertionError("source path resolved")), \
             mock.patch("subprocess.Popen", side_effect=AssertionError("process executed")), \
             mock.patch("importlib.import_module", side_effect=AssertionError("retained code imported")):
            expected = self.validate()
            self.assertEqual(inventory.validate_retained_sources(self.document["sources"], expected,
                             expected_revision=REVISION), expected["sources"])

    def test_loader_reads_only_explicit_regular_manifest(self):
        body = encoded(self.document)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_bytes(body)
            self.assertEqual(inventory.load_source_inventory(path,
                expected_sha256=hashlib.sha256(body).hexdigest(), expected_revision=REVISION), self.document)

    def test_loader_missing_path_and_bad_digest_do_not_fallback(self):
        body = encoded(self.document)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            with self.assertRaises(inventory.SourceInventoryError):
                inventory.load_source_inventory(path, expected_sha256=hashlib.sha256(body).hexdigest(),
                                                expected_revision=REVISION)
            path.write_bytes(body)
            with self.assertRaises(inventory.SourceInventoryError):
                inventory.load_source_inventory(path, expected_sha256="0" * 64, expected_revision=REVISION)

    def test_loader_rejects_symlink_file_and_parent(self):
        body = encoded(self.document)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "actual").mkdir()
            path = root / "actual/manifest.json"
            path.write_bytes(body)
            (root / "linked.json").symlink_to(path)
            (root / "linked-dir").symlink_to(root / "actual", target_is_directory=True)
            for selected in (root / "linked.json", root / "linked-dir/manifest.json"):
                with self.subTest(path=selected), self.assertRaises(inventory.SourceInventoryError):
                    inventory.load_source_inventory(selected, expected_revision=REVISION,
                        expected_sha256=hashlib.sha256(body).hexdigest())

    def test_loader_rejects_fifo_directory_and_oversized_sparse_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            os.mkfifo(root / "fifo")
            (root / "folder").mkdir()
            oversized = root / "oversized.json"
            with oversized.open("wb") as output:
                output.truncate(inventory.MAX_MANIFEST_BYTES + 1)
            for selected in (root / "fifo", root / "folder", oversized):
                with self.subTest(path=selected), self.assertRaises(inventory.SourceInventoryError):
                    inventory.load_source_inventory(selected, expected_revision=REVISION,
                                                    expected_sha256="0" * 64)

    def test_loader_rechecks_named_file_identity(self):
        body = encoded(self.document)
        original = inventory.PacketReader.read_bytes
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_bytes(body)

            def changed(reader, relative, limit):
                result = original(reader, relative, limit)
                replacement = path.with_name("replacement.json")
                replacement.write_bytes(body)
                replacement.replace(path)
                return result

            with mock.patch.object(inventory.PacketReader, "read_bytes", changed):
                with self.assertRaises(inventory.SourceInventoryError):
                    inventory.load_source_inventory(path, expected_revision=REVISION,
                        expected_sha256=hashlib.sha256(body).hexdigest())


if __name__ == "__main__":
    unittest.main()
