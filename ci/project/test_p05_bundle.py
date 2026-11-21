# SPDX-License-Identifier: Apache-2.0
"""Host-only receipt tests with inert bytes; no native or GPU qualification.

The fixture follows the W02 packaging receipt schema. Each test snapshots the
actual declared source bytes into its own temporary tree outside the checkout.
Synthetic library/module bytes are never imported, loaded, or executed.
"""

from contextlib import contextmanager
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
from types import MappingProxyType
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "python/vortex_ai"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUNDLE = load_module("_p05_bundle_host_tests", PACKAGE / "_bundle.py")
NATIVE_PATHS = {
    "runtime": "sw/runtime/libvortex.so",
    "backend": "sw/runtime/libvortex-simx.so",
    "simulator": "sw/runtime/libsimx.so",
    "ramulator": "third_party/ramulator/libramulator.so",
    "ramulator_extension": "third_party/ramulator_ext/libramulator-vortex.so",
    "module": "tests/regression/ai_mlp/kernel.vxbin",
}


def canonical(value):
    """Independent serialization used to create receipts, never to validate them."""
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def qualification_identity(binding):
    return hashlib.sha256(canonical(binding)[:-1]).hexdigest()


class BundleFixture:
    """An independently hashed source snapshot and nonexecutable receipt inputs."""

    def __init__(self, directory, fmt="fp16"):
        self.area = Path(directory)
        self.source = self.area / "source"
        self.root = self.area / "bundle"
        self.source.mkdir()
        self.root.mkdir()
        self.source_bytes = MappingProxyType({path: (ROOT / path).read_bytes()
                                             for path in BUNDLE.SOURCE_PATHS})
        inventory = []
        for relative, raw in self.source_bytes.items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            inventory.append({"path": relative, "sha256": hashlib.sha256(raw).hexdigest(),
                              "size": len(raw)})
        artifacts, native, dependencies = [], [], []
        for role, relative in sorted(BUNDLE.ROLES.items()):
            raw = ("P05 HOST-ONLY SYNTHETIC METADATA INPUT: " + role + "\n").encode()
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            artifacts.append(dict(role=role, path=relative, sha256=digest, size=len(raw)))
            record = dict(path=NATIVE_PATHS[role], sha256=digest, size_bytes=len(raw))
            (dependencies if role.startswith("ramulator") else native).append(record)
        binding = {
            "source": {"revision": "1" * 40, "tree": "2" * 40, "dirty": False},
            "backend": "simx", "format": fmt,
            "compiler_records": [{"scope": "host-only synthetic packaging input"}],
            "artifacts": native, "dependencies": dependencies,
            "profile_sha256": BUNDLE.PROFILE_SHA256,
            "fixture_sha256": BUNDLE.FIXTURE_SHA256, "model_id": "p04-tiny-mlp-v1",
        }
        self.manifest = {
            "schema_version": 1, "contract_id": BUNDLE.CONTRACT_ID,
            "backend": "simx", "format": fmt,
            "source_revision": "1" * 40, "source_tree": "2" * 40,
            "binding_sources": inventory,
            "binding_source_sha256": hashlib.sha256(canonical(inventory)).hexdigest(),
            "profile_sha256": BUNDLE.PROFILE_SHA256,
            "fixture_sha256": BUNDLE.FIXTURE_SHA256,
            "qualification_id": qualification_identity(binding),
            "native_binding": binding, "artifacts": artifacts,
        }
        self.write()

    def write(self, data=None, *, rebind=False, reinventory=False):
        data = self.manifest if data is None else data
        if rebind:
            data["qualification_id"] = qualification_identity(data["native_binding"])
        if reinventory:
            data["binding_source_sha256"] = hashlib.sha256(
                canonical(data["binding_sources"])).hexdigest()
        raw = canonical(data)
        (self.root / "manifest.json").write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    @property
    def identity(self):
        return dict(binding_api=1, bundle_sha256=hashlib.sha256(
            (self.root / "manifest.json").read_bytes()).hexdigest(),
            source_sha256=self.manifest["binding_source_sha256"])


@contextmanager
def isolated_package():
    """Restore every package module, including any caller's real native module."""
    saved = {name: value for name, value in tuple(sys.modules.items())
             if name == "vortex_ai" or name.startswith("vortex_ai.")}
    for name in saved:
        del sys.modules[name]
    package = types.ModuleType("vortex_ai")
    package.__path__ = [str(PACKAGE)]
    sys.modules["vortex_ai"] = package
    try:
        yield package
    finally:
        for name in tuple(sys.modules):
            if name == "vortex_ai" or name.startswith("vortex_ai."):
                del sys.modules[name]
        sys.modules.update(saved)


class BundleTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p05-bundle-host-only-")
        self.addCleanup(temporary.cleanup)
        self.fixture = BundleFixture(temporary.name)
        self.root = self.fixture.root

    def rejected(self, data, *, rebind=False, reinventory=False):
        self.fixture.write(data, rebind=rebind, reinventory=reinventory)
        with self.assertRaises(BUNDLE.BundleError):
            BUNDLE.read_manifest(self.root)


class BundleManifestTests(BundleTestCase):
    def test_canonical_serialization_is_sorted_compact_and_newline_terminated(self):
        self.assertEqual(BUNDLE.canonical_bytes({"z": 1, "a": "\u2603"}),
                         b'{"a":"\\u2603","z":1}\n')
        for number in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(number=number), self.assertRaises(ValueError):
                BUNDLE.canonical_bytes({"value": number})

    def test_complete_receipt_and_independent_source_identity(self):
        root, digest, data = BUNDLE.read_manifest(self.root)
        self.assertEqual(root, self.root.resolve())
        self.assertEqual(digest, self.fixture.identity["bundle_sha256"])
        self.assertEqual(data, self.fixture.manifest)
        self.assertEqual(BUNDLE.source_inventory(self.fixture.source), data["binding_sources"])
        self.assertEqual(BUNDLE.inventory_digest(data["binding_sources"]),
                         data["binding_source_sha256"])
        self.assertEqual(BUNDLE.build_binding(self.root, self.fixture.source),
                         (digest, data["binding_source_sha256"]))
        self.assertFalse(self.fixture.source.resolve().is_relative_to(ROOT))

    def test_both_declared_formats_have_distinct_native_and_manifest_identities(self):
        original = self.fixture.identity["bundle_sha256"]
        data = copy.deepcopy(self.fixture.manifest)
        data["format"] = data["native_binding"]["format"] = "bf16"
        changed = self.fixture.write(data, rebind=True)
        self.assertNotEqual(changed, original)
        self.assertNotEqual(data["qualification_id"], self.fixture.manifest["qualification_id"])
        self.assertEqual(BUNDLE.read_manifest(self.root)[2]["format"], "bf16")

    def test_receipt_root_and_manifest_must_exist_and_be_regular(self):
        for root in (self.root / "missing", self.root / "manifest.json", None, 8):
            with self.subTest(root=root), self.assertRaises(BUNDLE.BundleError):
                BUNDLE.read_manifest(root)
        (self.root / "manifest.json").unlink()
        with self.assertRaises(BUNDLE.BundleError):
            BUNDLE.read_manifest(self.root)

    def test_noncanonical_json_is_rejected(self):
        raw = canonical(self.fixture.manifest)
        variants = [raw[:-1], raw + b"\n", b" " + raw,
                    json.dumps(self.fixture.manifest, indent=2).encode() + b"\n",
                    json.dumps(self.fixture.manifest, sort_keys=False,
                               separators=(",", ":")).encode() + b"\n",
                    b"\xef\xbb\xbf" + raw, raw.decode().encode("utf-16"),
                    raw.decode().encode("utf-32")]
        for index, value in enumerate(variants):
            with self.subTest(variant=index):
                (self.root / "manifest.json").write_bytes(value)
                with self.assertRaises(BUNDLE.BundleError):
                    BUNDLE.read_manifest(self.root)

    def test_duplicate_json_keys_are_rejected_at_every_object_depth(self):
        raw = canonical(self.fixture.manifest)
        for token in (b'"schema_version":1', b'"backend":"simx"', b'"dirty":false',
                      b'"role":"backend"'):
            with self.subTest(token=token):
                self.assertIn(token, raw)
                (self.root / "manifest.json").write_bytes(raw.replace(token, token + b"," + token, 1))
                with self.assertRaises(BUNDLE.BundleError):
                    BUNDLE.read_manifest(self.root)

    def test_malformed_nonfinite_and_nonobject_json_are_rejected(self):
        for raw in (b"{\n", b"\xff\n", b"[]\n", b"null\n", b"1\n",
                    b'{"value":NaN}\n', b'{"value":Infinity}\n', b'{"value":-Infinity}\n'):
            with self.subTest(raw=raw):
                (self.root / "manifest.json").write_bytes(raw)
                with self.assertRaises(BUNDLE.BundleError):
                    BUNDLE.read_manifest(self.root)

    def test_excessively_nested_json_becomes_a_bundle_error(self):
        (self.root / "manifest.json").write_bytes(b"[" * 2000 + b"0" + b"]" * 2000 + b"\n")
        with self.assertRaises(BUNDLE.BundleError):
            BUNDLE.read_manifest(self.root)

    def test_manifest_requires_exact_top_level_keys(self):
        for key in sorted(BUNDLE.MANIFEST_KEYS):
            with self.subTest(missing=key):
                data = copy.deepcopy(self.fixture.manifest)
                del data[key]
                self.rejected(data)
        data = copy.deepcopy(self.fixture.manifest)
        data["trusted"] = True
        self.rejected(data)

    def test_schema_and_variant_fields_reject_type_confusion(self):
        bad = {
            "schema_version": (True, False, "1", 1.0, 0, 2, None),
            "contract_id": (None, True, [], "p05-python-bundle-v2"),
            "backend": (None, True, [], "rtlsim", "SIMX"),
            "format": (None, True, [], "fp32", "FP16"),
            "profile_sha256": (None, True, [], "0" * 64),
            "fixture_sha256": (None, True, [], "0" * 64),
        }
        for key, values in bad.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    data = copy.deepcopy(self.fixture.manifest)
                    data[key] = value
                    self.rejected(data)

    def test_hex_identities_require_exact_lowercase_lengths_and_strings(self):
        for key in ("source_revision", "source_tree", "binding_source_sha256", "qualification_id"):
            length = 40 if key in ("source_revision", "source_tree") else 64
            for value in (None, True, [], 1, "a" * (length - 1), "a" * (length + 1),
                          "A" * length, "g" * length, "a" * length + "\n"):
                with self.subTest(key=key, value=value):
                    data = copy.deepcopy(self.fixture.manifest)
                    data[key] = value
                    self.rejected(data)

    def test_source_inventory_requires_exact_order_membership_and_digest(self):
        for change in (lambda rows: rows.pop(), lambda rows: rows.reverse(),
                       lambda rows: rows.append(copy.deepcopy(rows[0])),
                       lambda rows: rows[0].update(path="../outside"),
                       lambda rows: rows[0].update(path="unlisted.py")):
            with self.subTest(change=change):
                data = copy.deepcopy(self.fixture.manifest)
                change(data["binding_sources"])
                self.rejected(data, reinventory=True)
        data = copy.deepcopy(self.fixture.manifest)
        data["binding_sources"][0]["sha256"] = "0" * 64
        self.rejected(data)

    def test_inventory_rows_require_exact_fields_types_and_positive_bounded_sizes(self):
        mutations = [("size", value) for value in (True, 0, -1, 1.0, "1", None, 256 * 1024 * 1024 + 1)]
        mutations += [("sha256", value) for value in (True, None, "x" * 64, "A" * 64, "a" * 63)]
        mutations += [("path", value) for value in (None, True, [], {})]
        for inventory in ("binding_sources", "artifacts"):
            for key, value in mutations:
                with self.subTest(inventory=inventory, key=key, value=value):
                    data = copy.deepcopy(self.fixture.manifest)
                    data[inventory][0][key] = value
                    self.rejected(data, reinventory=True)
            for value in (None, {}, [], "records", [None], [{}]):
                with self.subTest(inventory=inventory, rows=value):
                    data = copy.deepcopy(self.fixture.manifest)
                    data[inventory] = value
                    self.rejected(data)
            for mode in ("extra", "missing"):
                with self.subTest(inventory=inventory, mode=mode):
                    data = copy.deepcopy(self.fixture.manifest)
                    if mode == "extra":
                        data[inventory][0]["extra"] = 1
                    else:
                        del data[inventory][0]["sha256"]
                    self.rejected(data, reinventory=True)

    def test_six_roles_require_exact_membership_and_fixed_paths(self):
        changes = (
            lambda rows: rows.pop(), lambda rows: rows.append(copy.deepcopy(rows[0])),
            lambda rows: rows[0].update(role=rows[1]["role"]),
            lambda rows: rows[0].update(role="other"),
            lambda rows: rows[0].update(role=True),
            lambda rows: rows[0].update(role=[]),
            lambda rows: rows[0].update(path=rows[1]["path"]),
            lambda rows: rows[0].update(path="../outside"),
            lambda rows: rows[0].update(path="/absolute"),
        )
        for change in changes:
            with self.subTest(change=change):
                data = copy.deepcopy(self.fixture.manifest)
                change(data["artifacts"])
                self.rejected(data)

    def test_artifact_order_does_not_change_role_matching(self):
        data = copy.deepcopy(self.fixture.manifest)
        data["artifacts"].reverse()
        self.fixture.write(data)
        BUNDLE.validate_files(self.root, BUNDLE.read_manifest(self.root)[2])

    def test_native_binding_requires_exact_fields_and_its_own_identity(self):
        for key in self.fixture.manifest["native_binding"]:
            with self.subTest(missing=key):
                data = copy.deepcopy(self.fixture.manifest)
                del data["native_binding"][key]
                self.rejected(data, rebind=True)
        for value in (None, [], "binding", True):
            with self.subTest(binding=value):
                data = copy.deepcopy(self.fixture.manifest)
                data["native_binding"] = value
                self.rejected(data, rebind=True)
        data = copy.deepcopy(self.fixture.manifest)
        data["native_binding"]["extra"] = True
        self.rejected(data, rebind=True)
        data = copy.deepcopy(self.fixture.manifest)
        data["native_binding"]["compiler_records"][0]["changed"] = True
        self.rejected(data)

    def test_native_variant_must_agree_even_after_identity_is_recomputed(self):
        for key, value in (("format", "bf16"), ("backend", "rtlsim"),
                           ("profile_sha256", "0" * 64), ("fixture_sha256", "0" * 64),
                           ("model_id", "arbitrary-model")):
            with self.subTest(key=key):
                data = copy.deepcopy(self.fixture.manifest)
                data["native_binding"][key] = value
                self.rejected(data, rebind=True)

    def test_native_source_must_agree_and_dirty_must_be_literal_false(self):
        for key, values in (("revision", ("3" * 40, None, True)),
                            ("tree", ("4" * 40, None, True)),
                            ("dirty", (True, 0, None, "false"))):
            for value in values:
                with self.subTest(key=key, value=value):
                    data = copy.deepcopy(self.fixture.manifest)
                    data["native_binding"]["source"][key] = value
                    self.rejected(data, rebind=True)
        for value in (None, [], "source", {}):
            with self.subTest(source=value):
                data = copy.deepcopy(self.fixture.manifest)
                data["native_binding"]["source"] = value
                self.rejected(data, rebind=True)

    def test_native_compiler_records_must_be_a_nonempty_list(self):
        for value in (None, [], {}, "compiler", True):
            with self.subTest(value=value):
                data = copy.deepcopy(self.fixture.manifest)
                data["native_binding"]["compiler_records"] = value
                self.rejected(data, rebind=True)

    def test_every_native_artifact_digest_and_size_must_match_the_copied_role(self):
        for role, native_path in NATIVE_PATHS.items():
            for key in ("sha256", "size_bytes"):
                with self.subTest(role=role, key=key):
                    data = copy.deepcopy(self.fixture.manifest)
                    binding = data["native_binding"]
                    record = next(row for row in binding["artifacts"] + binding["dependencies"]
                                  if row["path"] == native_path)
                    record[key] = "0" * 64 if key == "sha256" else record[key] + 1
                    self.rejected(data, rebind=True)

    def test_native_records_require_exact_shape_and_no_cross_inventory_duplicates(self):
        for inventory in ("artifacts", "dependencies"):
            for value in (None, [], {}, [None], [{}]):
                with self.subTest(inventory=inventory, value=value):
                    data = copy.deepcopy(self.fixture.manifest)
                    data["native_binding"][inventory] = value
                    self.rejected(data, rebind=True)
            for key, value in (("size_bytes", True), ("size_bytes", 0),
                               ("size_bytes", 256 * 1024 * 1024 + 1),
                               ("sha256", "A" * 64), ("path", None)):
                with self.subTest(inventory=inventory, key=key):
                    data = copy.deepcopy(self.fixture.manifest)
                    data["native_binding"][inventory][0][key] = value
                    self.rejected(data, rebind=True)
            data = copy.deepcopy(self.fixture.manifest)
            row = data["native_binding"][inventory][0]
            row["size"] = row.pop("size_bytes")
            self.rejected(data, rebind=True)
        data = copy.deepcopy(self.fixture.manifest)
        data["native_binding"]["dependencies"].append(
            copy.deepcopy(data["native_binding"]["artifacts"][0]))
        self.rejected(data, rebind=True)

    def test_missing_selected_native_artifacts_are_rejected(self):
        for role, path in NATIVE_PATHS.items():
            with self.subTest(role=role):
                data = copy.deepcopy(self.fixture.manifest)
                for key in ("artifacts", "dependencies"):
                    data["native_binding"][key] = [row for row in data["native_binding"][key]
                                                   if row["path"] != path]
                self.rejected(data, rebind=True)

    def test_all_native_metadata_paths_require_safe_canonical_relative_syntax(self):
        for path in ("../escape", "/absolute", "a/../escape", "./same", "a//b",
                     "a/./b", "trailing/", "a\\b", "bad\npath", "bad\x00path", ""):
            for inventory in ("artifacts", "dependencies"):
                with self.subTest(path=path, inventory=inventory):
                    data = copy.deepcopy(self.fixture.manifest)
                    data["native_binding"][inventory].append(
                        dict(path=path, sha256="a" * 64, size_bytes=1))
                    self.rejected(data, rebind=True)

    def test_manifest_digest_detects_changed_bytes_between_observations(self):
        original = BUNDLE.read_file

        def disagreeing_read(root, relative, **kwargs):
            record, raw = original(root, relative, **kwargs)
            return record, raw + b" "

        with mock.patch.object(BUNDLE, "read_file", side_effect=disagreeing_read):
            with self.assertRaisesRegex(BUNDLE.BundleError, "manifest changed"):
                BUNDLE.read_manifest(self.root)

    def test_manifest_uses_one_nonblocking_handle_without_an_unbounded_reopen(self):
        original = BUNDLE.os.open
        with mock.patch.object(BUNDLE.os, "open", wraps=original) as opened, \
                mock.patch.object(Path, "read_bytes", side_effect=AssertionError("unbounded reopen")):
            BUNDLE.read_manifest(self.root)
        opened.assert_called_once()
        self.assertEqual(Path(opened.call_args.args[0]), self.root / "manifest.json")
        flags = opened.call_args.args[1]
        for required in (os.O_NOFOLLOW, os.O_NONBLOCK, os.O_CLOEXEC):
            self.assertEqual(flags & required, required)

    def test_manifest_path_replacement_is_detected_even_with_identical_bytes(self):
        original = BUNDLE.os.fstat
        raw = canonical(self.fixture.manifest)
        calls = 0

        def replace_after_final_descriptor_stat(descriptor):
            nonlocal calls
            info = original(descriptor)
            calls += 1
            if calls == 2:
                path = self.root / "manifest.json"
                path.rename(self.root / "old-manifest.json")
                path.write_bytes(raw)
            return info

        with mock.patch.object(BUNDLE.os, "fstat", side_effect=replace_after_final_descriptor_stat):
            with self.assertRaisesRegex(BUNDLE.BundleError, "changed"):
                BUNDLE.read_manifest(self.root)
        self.assertEqual(calls, 2)


class BundleFilesystemTests(BundleTestCase):
    def test_file_record_independently_hashes_exact_content(self):
        for relative in BUNDLE.ROLES.values():
            with self.subTest(relative=relative):
                raw = (self.root / relative).read_bytes()
                self.assertEqual(BUNDLE.file_record(self.root, relative),
                                 dict(path=relative, sha256=hashlib.sha256(raw).hexdigest(), size=len(raw)))

    def test_all_six_files_are_checked_for_mutation(self):
        for relative in BUNDLE.ROLES.values():
            with self.subTest(relative=relative):
                path = self.root / relative
                original = path.read_bytes()
                path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
                with self.assertRaises(BUNDLE.BundleError):
                    BUNDLE.validate_files(self.root, self.fixture.manifest)
                path.write_bytes(original)

    def test_all_six_required_files_must_be_present(self):
        for relative in BUNDLE.ROLES.values():
            with self.subTest(relative=relative):
                path = self.root / relative
                original = path.read_bytes()
                path.unlink()
                with self.assertRaises(BUNDLE.BundleError):
                    BUNDLE.validate_files(self.root, self.fixture.manifest)
                path.write_bytes(original)

    def test_all_six_files_reject_symlinks_even_to_identical_bytes(self):
        for relative in BUNDLE.ROLES.values():
            with self.subTest(relative=relative):
                path = self.root / relative
                original = path.read_bytes()
                target = self.fixture.area / "outside-artifact"
                target.write_bytes(original)
                path.unlink()
                path.symlink_to(target)
                try:
                    with self.assertRaises(BUNDLE.BundleError):
                        BUNDLE.validate_files(self.root, self.fixture.manifest)
                finally:
                    path.unlink()
                    path.write_bytes(original)

    def test_library_directory_rejects_extra_entries_of_every_kind(self):
        extra = self.root / "lib/.unexpected"
        for kind in ("file", "directory", "symlink"):
            with self.subTest(kind=kind):
                if kind == "file":
                    extra.write_bytes(b"extra")
                elif kind == "directory":
                    extra.mkdir()
                else:
                    extra.symlink_to(self.root / "lib/libsimx.so")
                try:
                    with self.assertRaises(BUNDLE.BundleError):
                        BUNDLE.validate_files(self.root, self.fixture.manifest)
                finally:
                    extra.rmdir() if kind == "directory" else extra.unlink()

    def test_library_directory_itself_cannot_be_a_symlink(self):
        directory = self.root / "lib"
        moved = self.fixture.area / "external-lib"
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(BUNDLE.BundleError):
            BUNDLE.validate_files(self.root, self.fixture.manifest)

    def test_file_paths_reject_escapes_controls_noncanonical_forms_and_nonstrings(self):
        for value in ("../manifest.json", "/etc/passwd", "lib/../manifest.json",
                      "./manifest.json", "lib//libvortex.so", "lib/./libvortex.so",
                      "lib/libvortex.so/", "lib\\libvortex.so", "bad\npath", "bad\x00path",
                      "", ".", "..", None, True, 3, [], {}):
            with self.subTest(path=value), self.assertRaises(BUNDLE.BundleError):
                BUNDLE.file_record(self.root, value)

    def test_regular_file_type_and_size_bounds_precede_reading(self):
        path = self.root / "probe"
        for kind in ("empty", "directory", "too-large"):
            with self.subTest(kind=kind):
                if kind == "directory":
                    path.mkdir()
                else:
                    path.write_bytes(b"" if kind == "empty" else b"0123456789")
                try:
                    with self.assertRaises(BUNDLE.BundleError):
                        BUNDLE.file_record(self.root, "probe", limit=4)
                finally:
                    path.rmdir() if kind == "directory" else path.unlink()

    def test_module_requires_sixteen_bytes_even_with_a_consistent_receipt(self):
        for size in (1, 15, 16):
            with self.subTest(size=size):
                data = copy.deepcopy(self.fixture.manifest)
                raw = b"x" * size
                (self.root / "kernel.vxbin").write_bytes(raw)
                digest = hashlib.sha256(raw).hexdigest()
                next(row for row in data["artifacts"] if row["role"] == "module").update(
                    sha256=digest, size=size)
                next(row for row in data["native_binding"]["artifacts"]
                     if row["path"] == NATIVE_PATHS["module"]).update(sha256=digest, size_bytes=size)
                self.fixture.write(data, rebind=True)
                manifest = BUNDLE.read_manifest(self.root)[2]
                if size < 16:
                    with self.assertRaises(BUNDLE.BundleError):
                        BUNDLE.validate_files(self.root, manifest)
                else:
                    BUNDLE.validate_files(self.root, manifest)

    def test_module_uses_its_smaller_size_bound(self):
        original = BUNDLE.file_record
        with mock.patch.object(BUNDLE, "file_record", wraps=original) as checked:
            BUNDLE.validate_files(self.root, self.fixture.manifest)
        self.assertEqual(len(checked.call_args_list), 6)
        for call in checked.call_args_list:
            expected_limit = 16 if call.args[1] == "kernel.vxbin" else 256
            self.assertEqual(call.kwargs["limit"], expected_limit * 1024 * 1024)

    def test_file_changes_during_verification_are_rejected(self):
        original = BUNDLE.os.fstat
        calls = 0

        def change_after_final_descriptor_stat(descriptor):
            nonlocal calls
            info = original(descriptor)
            calls += 1
            if calls == 2:
                path = self.root / "kernel.vxbin"
                path.write_bytes(path.read_bytes() + b"changed")
            return info

        with mock.patch.object(BUNDLE.os, "fstat", side_effect=change_after_final_descriptor_stat):
            with self.assertRaisesRegex(BUNDLE.BundleError, "changed"):
                BUNDLE.file_record(self.root, "kernel.vxbin")
        self.assertEqual(calls, 2)

    def test_open_failures_are_reported_as_bundle_errors(self):
        with mock.patch.object(BUNDLE.os, "open", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(BUNDLE.BundleError, "cannot read required file"):
                BUNDLE.file_record(self.root, "kernel.vxbin")

    def test_all_six_fifos_and_fifo_manifest_are_rejected_without_blocking(self):
        code = """
import importlib.util, os, pathlib, sys
spec = importlib.util.spec_from_file_location('bundle_test', sys.argv[1])
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)
root = pathlib.Path(sys.argv[2])
for relative in [*bundle.ROLES.values(), 'manifest.json']:
    path = root / relative
    saved = path.read_bytes()
    path.unlink()
    os.mkfifo(path)
    try:
        try:
            bundle.file_record(root, relative)
        except bundle.BundleError:
            pass
        else:
            raise AssertionError('accepted FIFO: ' + relative)
    finally:
        path.unlink()
        path.write_bytes(saved)
print('seven FIFOs rejected')
"""
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code,
                                 str(PACKAGE / "_bundle.py"), str(self.root)],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "seven FIFOs rejected\n")

    def test_manifest_is_not_reopened_as_a_blocking_fifo_after_verification(self):
        code = """
import importlib.util, os, pathlib, sys
spec = importlib.util.spec_from_file_location('bundle_test', sys.argv[1])
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)
root = pathlib.Path(sys.argv[2])
original = bundle.file_record
def replace_after_check(directory, relative, **kwargs):
    result = original(directory, relative, **kwargs)
    if relative == 'manifest.json':
        (root / relative).unlink()
        os.mkfifo(root / relative)
    return result
bundle.file_record = replace_after_check
try:
    bundle.read_manifest(root)
except bundle.BundleError:
    pass
print('bounded manifest read')
"""
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code,
                                 str(PACKAGE / "_bundle.py"), str(self.root)],
                                capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "bounded manifest read\n")

    def test_unchanged_bundle_can_be_relocated(self):
        identity = self.fixture.identity
        relocated = self.fixture.area / "relocated-bundle"
        self.root.rename(relocated)
        self.assertEqual(BUNDLE.build_binding(relocated, self.fixture.source),
                         (identity["bundle_sha256"], identity["source_sha256"]))


class BundleSourceBindingTests(BundleTestCase):
    def test_changed_actual_source_is_not_hidden_by_an_unchanged_inventory(self):
        for relative in ("python/vortex_ai/_api.py", "python/vortex_ai/torch_ops.py"):
            path = self.fixture.source / relative
            raw = path.read_bytes()
            path.write_bytes(raw + b"\n# local source mutation\n")
            try:
                with self.subTest(path=relative), self.assertRaisesRegex(BUNDLE.BundleError, "sources differ"):
                    BUNDLE.build_binding(self.root, self.fixture.source)
            finally:
                path.write_bytes(raw)

    def test_rehashed_but_inaccurate_source_inventory_is_rejected(self):
        data = copy.deepcopy(self.fixture.manifest)
        data["binding_sources"][0]["sha256"] = "0" * 64
        self.fixture.write(data, reinventory=True)
        BUNDLE.read_manifest(self.root)
        with self.assertRaisesRegex(BUNDLE.BundleError, "sources differ"):
            BUNDLE.build_binding(self.root, self.fixture.source)

    def test_missing_declared_source_is_rejected(self):
        (self.fixture.source / BUNDLE.SOURCE_PATHS[0]).unlink()
        with self.assertRaises(BUNDLE.BundleError):
            BUNDLE.build_binding(self.root, self.fixture.source)

    def test_source_symlink_is_rejected_even_when_hashes_match(self):
        path = self.fixture.source / BUNDLE.SOURCE_PATHS[0]
        external = self.fixture.area / "external-source"
        external.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(external)
        with self.assertRaises(BUNDLE.BundleError):
            BUNDLE.build_binding(self.root, self.fixture.source)

    def test_source_parent_symlink_is_rejected(self):
        parent = self.fixture.source / "python"
        external = self.fixture.area / "external-python"
        parent.rename(external)
        parent.symlink_to(external, target_is_directory=True)
        with self.assertRaises(BUNDLE.BundleError):
            BUNDLE.build_binding(self.root, self.fixture.source)


if __name__ == "__main__":
    unittest.main()
