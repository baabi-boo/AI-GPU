# Licensed under the Apache License, Version 2.0.
"""Independent contract and filesystem mutation tests; no vendor execution."""

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import xrt_contract as contract
from xrt_test_support import VendorFixture, write_file, write_json


class ContractFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ai-gpu-xrt-contract-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.fixture = VendorFixture(self.base)

    def assert_invalid_manifest(self, mutate):
        data = copy.deepcopy(self.fixture.manifest)
        mutate(data)
        with self.assertRaises(ValueError):
            contract.validate_manifest(data)

    def assert_invalid_receipt(self, mutate):
        data = copy.deepcopy(self.fixture.receipt)
        mutate(data)
        with self.assertRaises(ValueError):
            contract.validate_receipt(data, self.fixture.manifest)


class ManifestTests(ContractFixture):
    def test_synthetic_manifest_round_trip_is_structural_only(self):
        self.assertEqual(contract.load_manifest(self.fixture.manifest_path), self.fixture.manifest)
        self.assertNotIn("phase_complete", self.fixture.manifest)
        self.assertIn("No vendor qualification", Path(
            self.fixture.manifest["qualification_review"]["path"]).read_text())

    def test_validation_does_not_open_files_or_mutate_input(self):
        data = copy.deepcopy(self.fixture.manifest)
        with mock.patch.object(contract, "_open_regular", side_effect=AssertionError("unexpected I/O")):
            self.assertEqual(contract.validate_manifest(data), self.fixture.manifest)
            contract.validate_receipt(self.fixture.receipt, data)
        self.assertEqual(data, self.fixture.manifest)

    def test_rejects_other_execution_scopes(self):
        for key, values in (("driver", ["simx", "rtlsim", "gpu", "XRT"]),
                            ("target", ["xrtsim", "hw", "sw_emu", "", None]),
                            ("id", ["p02", "p01-hw-emu-demo-v0"])):
            for value in values:
                with self.subTest(key=key, value=value):
                    self.assert_invalid_manifest(lambda data: data.__setitem__(key, value))

    def test_rejects_schema_version_type_coercion(self):
        for value in (True, 1.0, "1", 0, 2, None):
            with self.subTest(value=value):
                self.assert_invalid_manifest(lambda data: data.__setitem__("schema_version", value))

    def test_rejects_altered_workload_or_configuration(self):
        mutations = [("xlen", 32), ("xlen", 64.0), ("app", "sgemm"),
                     ("args", ["-n16"]), ("args", ["-n1", "--fake"]),
                     ("expected_points", 64), ("expected_points", 16.0),
                     ("configs", list(reversed(self.fixture.manifest["configuration"]["configs"]))),
                     ("configs", self.fixture.manifest["configuration"]["configs"] + ["-DXRTSIM"])]
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                self.assert_invalid_manifest(lambda data: data["configuration"].__setitem__(key, value))

    def test_rejects_missing_and_unknown_fields_at_each_boundary(self):
        routes = [(), ("source",), ("configuration",), ("platform",),
                  ("platform", "file"), ("vendor",), ("vendor", "files"),
                  ("vendor", "files", "vpp"), ("artifacts",),
                  ("artifacts", "emconfig"), ("build_receipt",), ("qualification_review",)]
        for route in routes:
            for mode in ("missing", "unknown"):
                with self.subTest(route=route, mode=mode):
                    def mutate(data):
                        for key in route:
                            data = data[key]
                        if mode == "missing":
                            data.pop(next(iter(data)))
                        else:
                            data["unexpected"] = True
                    self.assert_invalid_manifest(mutate)

    def test_rejects_malformed_source_identities(self):
        for key in ("revision", "tree"):
            for value in ("a" * 39, "a" * 41, "A" * 40, "g" * 40, None, 123):
                with self.subTest(key=key, value=value):
                    self.assert_invalid_manifest(lambda data: data["source"].__setitem__(key, value))

    def test_rejects_file_digest_or_size_type_errors(self):
        changes = [("sha256", "a" * 63), ("sha256", "A" * 64), ("sha256", 1),
                   ("size_bytes", 0), ("size_bytes", -1), ("size_bytes", True),
                   ("size_bytes", 1.0), ("size_bytes", 16 * 1024**3 + 1)]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                self.assert_invalid_manifest(lambda data: data["artifacts"]["xclbin"].__setitem__(key, value))

    def test_small_json_and_review_inputs_have_separate_limits(self):
        for route in (("artifacts", "emconfig"), ("build_receipt",), ("qualification_review",)):
            with self.subTest(route=route):
                def mutate(data):
                    for key in route:
                        data = data[key]
                    data["size_bytes"] = 1024**2 + 1
                self.assert_invalid_manifest(mutate)

    def test_rejects_wrong_artifact_names_and_separate_directories(self):
        for role, value in (("xclbin", str(self.base / "artifacts/other.xclbin")),
                            ("emconfig", str(self.base / "artifacts/other.json")),
                            ("emconfig", str(self.base / "elsewhere/emconfig.json"))):
            with self.subTest(role=role, value=value):
                self.assert_invalid_manifest(lambda data: data["artifacts"][role].__setitem__("path", value))

    def test_rejects_wrong_platform_suffix(self):
        self.assert_invalid_manifest(lambda data: data["platform"]["file"].__setitem__(
            "path", str(self.base / "platform.xsa")))

    def test_rejects_unsafe_labels(self):
        for route in (("platform", "name"), ("vendor", "release")):
            for value in ("", "space label", "$(command)", "a\nlabel", "a" * 129, 12):
                with self.subTest(route=route, value=value):
                    self.assert_invalid_manifest(lambda data: data[route[0]].__setitem__(route[1], value))

    def test_rejects_unsafe_paths(self):
        values = ["relative/file", "/tmp/../artifact", "/tmp/./artifact", "/tmp//artifact",
                  "/tmp/artifact/", "/tmp/a b", "/tmp/$(command)", "/tmp/`command`",
                  "/tmp/with;command", "/tmp/a\nfile", "/tmp/a\x00file", "", None, 123]
        for value in values:
            with self.subTest(value=value):
                self.assert_invalid_manifest(lambda data: data["build_receipt"].__setitem__("path", value))

    def test_paths_are_not_implicitly_stringified(self):
        self.assert_invalid_manifest(lambda data: data["build_receipt"].__setitem__(
            "path", Path(data["build_receipt"]["path"])))
        self.assert_invalid_manifest(lambda data: data["vendor"].__setitem__("xrt_root", self.fixture.xrt))


class ReceiptTests(ContractFixture):
    def test_matching_synthetic_receipt_loads(self):
        self.assertEqual(contract.load_receipt(self.fixture.receipt_path, self.fixture.manifest),
                         self.fixture.receipt)

    def test_rejects_each_independently_mismatched_identity(self):
        changes = [(("source", "revision"), "c" * 40), (("source", "tree"), "c" * 40),
                   (("platform", "name"), "different_platform"),
                   (("platform", "file", "sha256"), "c" * 64),
                   (("vendor", "release"), "different_release"),
                   (("vendor", "files", "vpp", "sha256"), "c" * 64),
                   (("artifacts", "xclbin", "sha256"), "c" * 64),
                   (("artifacts", "emconfig", "sha256"), "c" * 64)]
        for route, value in changes:
            with self.subTest(route=route):
                def mutate(data):
                    for key in route[:-1]:
                        data = data[key]
                    data[route[-1]] = value
                self.assert_invalid_receipt(mutate)

    def test_wrong_scope_or_failed_build_cannot_be_a_receipt(self):
        for key, value in (("driver", "simx"), ("target", "xrtsim"), ("target", "hw")):
            with self.subTest(key=key, value=value):
                self.assert_invalid_receipt(lambda data: data.__setitem__(key, value))
        for value in (1, -1, None, False, 0.0, "0"):
            with self.subTest(exit_code=value):
                self.assert_invalid_receipt(lambda data: data["commands"][0].__setitem__("exit_code", value))

    def test_receipt_requires_bounded_command_records(self):
        for value in ([], None, {}, [self.fixture.receipt["commands"][0]] * 33):
            with self.subTest(value_type=type(value), length=len(value) if value is not None else None):
                self.assert_invalid_receipt(lambda data: data.__setitem__("commands", value))
        for argv in ([], "command", [""], ["x\n"], ["x\x00"], ["x\x7f"], ["x" * 4097],
                     ["arg"] * 129, ["x" * 4096] * 9, [42]):
            with self.subTest(argv=repr(argv)[:100]):
                self.assert_invalid_receipt(lambda data: data["commands"][0].__setitem__("argv", argv))

    def test_receipt_unknown_keys_and_missing_log_rejected(self):
        for mutate in (lambda data: data.__setitem__("unexpected", 1),
                       lambda data: data["commands"][0].__setitem__("environment", {}),
                       lambda data: data["commands"][0].pop("log"),
                       lambda data: data["commands"][0].__setitem__("cwd", "relative")):
            with self.subTest(mutation=mutate):
                self.assert_invalid_receipt(mutate)

    def test_receipt_command_text_is_inert(self):
        data = copy.deepcopy(self.fixture.receipt)
        data["commands"][0]["argv"] = ["$(touch", str(self.base / "unwanted"), ")"]
        contract.validate_receipt(data, self.fixture.manifest)
        self.assertFalse((self.base / "unwanted").exists())

    def test_rejects_loading_a_different_receipt_path(self):
        alternate = self.base / "alternate-receipt.json"
        write_json(alternate, self.fixture.receipt)
        with self.assertRaises(ValueError):
            contract.load_receipt(alternate, self.fixture.manifest)

    def test_load_receipt_checks_actual_digest(self):
        self.fixture.receipt_path.write_text(json.dumps(self.fixture.receipt) + " ")
        with self.assertRaises(ValueError):
            contract.load_receipt(self.fixture.receipt_path, self.fixture.manifest)


class JsonTests(unittest.TestCase):
    def test_duplicate_root_and_nested_fields_are_rejected(self):
        for contents in (b'{"id":1,"id":2}', b'{"outer":{"key":1,"key":2}}'):
            with self.subTest(contents=contents), self.assertRaises(ValueError):
                contract.decode_json(contents)

    def test_nonfinite_values_including_overflow_are_rejected(self):
        for value in ("NaN", "Infinity", "-Infinity", "1e9999", "-1e9999"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                contract.decode_json(('{"nested":{"value":' + value + '}}').encode())

    def test_malformed_encoding_or_root_is_rejected(self):
        for contents in (b"not-json", b'{"x":"\xff"}', b"[]", b"1", b"null"):
            with self.subTest(contents=repr(contents[:80])), self.assertRaises(ValueError):
                contract.decode_json(contents)

    def test_decoder_recursion_failure_becomes_input_error(self):
        with mock.patch.object(contract.json, "loads", side_effect=RecursionError):
            with self.assertRaises(ValueError):
                contract.decode_json(b'{"nested":{}}')

    def test_json_must_be_bounded_bytes(self):
        for contents in ("{}", bytearray(b"{}"), b" " * (1024**2 + 1)):
            with self.subTest(kind=type(contents)), self.assertRaises(ValueError):
                contract.decode_json(contents)

    def test_finite_json_number_and_unicode_remain_supported(self):
        self.assertEqual(contract.decode_json('{"ratio":1.25,"label":"α"}'.encode()),
                         {"ratio": 1.25, "label": "α"})


class FileInspectionTests(ContractFixture):
    def test_identity_and_verified_bytes_match_independent_hash(self):
        path = self.base / "binary.bin"
        contents = bytes(range(256)) * 300
        expected = write_file(path, contents)
        self.assertEqual(contract.file_identity(path),
                         {"sha256": hashlib.sha256(contents).hexdigest(), "size_bytes": len(contents)})
        self.assertEqual(contract.read_verified(expected), contents)

    def test_verified_content_rejects_hash_and_size_mismatch(self):
        original = write_file(self.base / "file", b"known bytes")
        for key, value in (("sha256", "f" * 64), ("size_bytes", original["size_bytes"] + 1)):
            record = dict(original, **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                contract.read_verified(record)

    def test_empty_file_identity_is_not_valid_declared_content(self):
        record = write_file(self.base / "empty", b"")
        self.assertEqual(contract.file_identity(record["path"])["size_bytes"], 0)
        with self.assertRaises(ValueError):
            contract.read_verified(record)

    def test_rejects_leaf_and_parent_symlinks(self):
        real = self.base / "real"
        real.mkdir()
        write_file(real / "file", "data")
        (self.base / "leaf-link").symlink_to(real / "file")
        (self.base / "parent-link").symlink_to(real, target_is_directory=True)
        for path in (self.base / "leaf-link", self.base / "parent-link/file"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                contract.file_identity(path)

    def test_rejects_directories_and_missing_files(self):
        for path in (self.base, self.base / "missing"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                contract.file_identity(path)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO test requires POSIX")
    def test_fifo_is_rejected_without_waiting_for_writer(self):
        path = self.base / "fifo"
        os.mkfifo(path)
        with self.assertRaises(ValueError):
            contract.file_identity(path)

    def test_rejects_oversized_file_before_unbounded_read(self):
        path = self.base / "large"
        with path.open("wb") as stream:
            stream.truncate(1024**2 + 1)
        with self.assertRaises(ValueError):
            contract.file_identity(path, max_bytes=1024**2)
        with self.assertRaises(ValueError):
            contract.load_json(path)

    def test_rejects_invalid_explicit_limits(self):
        path = self.base / "small"
        record = write_file(path, "x")
        for value in (0, -1, True, 1.0, "1", 16 * 1024**3 + 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                contract.file_identity(path, max_bytes=value)
        for value in (0, True, 1024**2 + 1):
            with self.subTest(json_limit=value), self.assertRaises(ValueError):
                contract.load_json(path, max_bytes=value)
        with self.assertRaises(ValueError):
            contract.read_verified(record, max_bytes=16 * 1024**2 + 1)

    def test_detects_same_size_mutation_during_read(self):
        path = self.base / "mutable"
        write_file(path, b"a" * 100000)
        read = os.read
        mutated = False

        def mutate(descriptor, count):
            nonlocal mutated
            block = read(descriptor, count)
            if block and not mutated:
                mutated = True
                path.write_bytes(b"b" * 100000)
            return block

        with mock.patch.object(contract.os, "read", side_effect=mutate):
            with self.assertRaises(ValueError):
                contract.file_identity(path)
        self.assertTrue(mutated)

    def test_detects_atomic_path_replacement_during_read(self):
        path = self.base / "replaced"
        write_file(path, b"original")
        replacement = self.base / "replacement"
        write_file(replacement, b"replaced")
        read = os.read
        replaced = False

        def replace(descriptor, count):
            nonlocal replaced
            block = read(descriptor, count)
            if block and not replaced:
                replaced = True
                replacement.replace(path)
            return block

        with mock.patch.object(contract.os, "read", side_effect=replace):
            with self.assertRaises(ValueError):
                contract.file_identity(path)
        self.assertTrue(replaced)

    def test_detects_growth_past_selected_limit(self):
        path = self.base / "growing"
        write_file(path, b"1234")
        read = os.read
        grown = False

        def grow(descriptor, count):
            nonlocal grown
            block = read(descriptor, count)
            if block and not grown:
                grown = True
                with path.open("ab") as stream:
                    stream.write(b"56789")
            return block

        with mock.patch.object(contract.os, "read", side_effect=grow):
            with self.assertRaises(ValueError):
                contract.file_identity(path, max_bytes=8)
        self.assertTrue(grown)

    def test_verified_read_uses_hash_of_returned_content(self):
        path = self.base / "content"
        record = write_file(path, b"trusted")
        path.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            contract.read_verified(record)


if __name__ == "__main__":
    unittest.main()
