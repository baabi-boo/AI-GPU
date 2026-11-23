# SPDX-License-Identifier: Apache-2.0
"""Test externally pinned Git-export receipts and inert retained source binding."""

from contextlib import ExitStack
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import p06_managed_preflight_derivation as derivation
import p06_managed_preflight_sources as inventory


ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "docs/project/evidence/p06-managed-preflight/native"
ORIGINAL = NATIVE / "run-45085300171-attempt1.zip"
ORIGINAL_SHA256 = "cee5be4dba875494f6eafb83484933ab7693428e4773b932a26d5b91bd17969d"
REVISION = "57248e73dfce4ae2d21d2cbdb82c3953eef2e3db"
MANIFEST = NATIVE / "source-inventory-57248e73.json"
MANIFEST_SHA256 = "72ca7e9237060ca2831a275811d27ec6fdb3507dfd9a00b693aa177aa68382e8"
RECEIPT = NATIVE / "source-derivation-57248e73.json"
RECEIPT_SHA256 = "3b25d30eceeee2dc5cebd1cce8ed7ab90da0fec64857e82fc7cc7fc3ca38e171"


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


class SourceDerivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = inventory.load_source_inventory(MANIFEST,
            expected_sha256=MANIFEST_SHA256, expected_revision=REVISION)
        cls.receipt = derivation.load_source_derivation(RECEIPT,
            expected_sha256=RECEIPT_SHA256, expected_revision=REVISION,
            source_inventory=cls.manifest, source_inventory_sha256=MANIFEST_SHA256)
        if hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() != ORIGINAL_SHA256:
            raise AssertionError("the original archive fixture digest differs")
        with zipfile.ZipFile(ORIGINAL) as archive:
            report = json.loads(archive.read("managed-preflight/report.json"))
            cls.checkout = json.loads(archive.read("managed-preflight/" +
                report["source_before"]["path"]))["checkout"]

    def decode(self, document, **overrides):
        body = document if type(document) is bytes else json_bytes(document)
        arguments = {"expected_sha256": hashlib.sha256(body).hexdigest(),
            "expected_revision": REVISION, "source_inventory": self.manifest,
            "source_inventory_sha256": MANIFEST_SHA256}
        arguments.update(overrides)
        return derivation.decode_source_derivation(body, **arguments)

    def bind(self, receipt=None, checkout=None, source_transform=None):
        with zipfile.ZipFile(ORIGINAL) as archive:
            def body(name):
                raw = archive.read("managed-preflight/artifacts/source/" + name)
                return source_transform(name, raw) if source_transform else raw
            return derivation.validate_retained_derivation(
                self.receipt if receipt is None else receipt,
                checkout=self.checkout if checkout is None else checkout, source_body=body)

    def test_original_receipt_binds_tree_gitlinks_and_all_git_blobs(self):
        result = self.bind()
        self.assertEqual(result["source_tree"], "cd61992a845ad14cbebd24b930c5801f727d5b41")
        self.assertEqual(result["source_files_checked"], 999)
        self.assertEqual(result["repository_source_counts"],
            {"source": 806, "ramulator": 50, "softfloat": 7, "spdlog": 99, "yaml-cpp": 37})
        self.assertEqual(result["native_execution"], "not_run")
        for name in (*derivation.FALSE_CLAIMS, "retained_code_executed",
                     "remote_origin_authenticated", "git_object_membership_revalidated",
                     "dependency_compilation_provenance_verified"):
            self.assertIs(result[name], False)

    def test_rehashed_forged_checkout_tree_rejects(self):
        document = copy.deepcopy(self.receipt)
        document["repositories"]["source"]["tree"] = "1" * 40
        changed = self.decode(document)
        with self.assertRaisesRegex(derivation.SourceDerivationError, "derived checkout tree"):
            self.bind(changed)

    def test_changed_retained_checkout_tree_rejects(self):
        checkout = copy.deepcopy(self.checkout)
        checkout["tree"] = "1" * 40
        with self.assertRaisesRegex(derivation.SourceDerivationError, "derived checkout tree"):
            self.bind(checkout=checkout)

    def test_rehashed_forged_selected_gitlinks_reject(self):
        for name in ("ramulator", "softfloat"):
            document = copy.deepcopy(self.receipt)
            document["repositories"][name]["commit"] = "1" * 40
            changed = self.decode(document)
            with self.subTest(repository=name), self.assertRaisesRegex(
                    derivation.SourceDerivationError, "derived dependency Gitlink " + name):
                self.bind(changed)

    def test_retained_submodule_duplicates_and_missing_gitlink_reject(self):
        checkout = copy.deepcopy(self.checkout)
        checkout["submodules"]["entries"].append(copy.deepcopy(checkout["submodules"]["entries"][-1]))
        with self.assertRaisesRegex(derivation.SourceDerivationError, "submodule path is repeated"):
            self.bind(checkout=checkout)
        checkout = copy.deepcopy(self.checkout)
        checkout["submodules"]["entries"] = [row for row in checkout["submodules"]["entries"]
                                               if row["path"] != "third_party/ramulator"]
        with self.assertRaisesRegex(derivation.SourceDerivationError, "dependency Gitlink is absent"):
            self.bind(checkout=checkout)

    def test_source_revision_and_manifest_digest_are_external(self):
        for key, value, label in (("source_revision", "1" * 40, "source_revision"),
                ("manifest_sha256", "1" * 64, "manifest_sha256")):
            document = copy.deepcopy(self.receipt)
            document[key] = value
            with self.subTest(field=key), self.assertRaisesRegex(derivation.SourceDerivationError, label):
                self.decode(document)

    def test_invalid_external_expectations_reject_before_open(self):
        arguments = dict(expected_sha256=RECEIPT_SHA256, expected_revision=REVISION,
                         source_inventory=self.manifest, source_inventory_sha256=MANIFEST_SHA256)
        for key in ("expected_sha256", "expected_revision", "source_inventory_sha256"):
            changed = dict(arguments, **{key: True})
            with self.subTest(field=key), mock.patch.object(derivation, "PacketReader") as reader:
                with self.assertRaisesRegex(derivation.SourceDerivationError, "external source"):
                    derivation.load_source_derivation(RECEIPT, **changed)
                reader.assert_not_called()

    def test_external_digest_is_checked_before_json(self):
        with mock.patch.object(derivation, "load_json_bytes") as decoder:
            with self.assertRaisesRegex(derivation.SourceDerivationError, "external digest"):
                self.decode(b"not JSON", expected_sha256="0" * 64)
            decoder.assert_not_called()

    def test_rehashed_source_descriptor_mutation_rejects(self):
        document = copy.deepcopy(self.receipt)
        document["sources"][0]["sha256"] = "1" * 64
        with self.assertRaisesRegex(derivation.SourceDerivationError, "derived source descriptor.sha256"):
            self.decode(document)

    def test_rehashed_git_blob_mutation_reaches_blob_check(self):
        document = copy.deepcopy(self.receipt)
        document["sources"][0]["git_blob"] = "1" * 40
        changed = self.decode(document)
        with self.assertRaisesRegex(derivation.SourceDerivationError, "derived retained Git blob"):
            self.bind(changed)

    def test_retained_body_size_and_digest_reject(self):
        with self.assertRaisesRegex(derivation.SourceDerivationError, "retained source size"):
            self.bind(source_transform=lambda _name, body: body + b"x")
        with self.assertRaisesRegex(derivation.SourceDerivationError, "retained source SHA-256"):
            self.bind(source_transform=lambda _name, body: bytes([body[0] ^ 1]) + body[1:])

    def test_rehashed_repository_mapping_and_path_mutations_reject(self):
        for key, value, label in (("repository", "softfloat", "source repository"),
                ("repository_path", "../outside.py", "source repository path")):
            document = copy.deepcopy(self.receipt)
            document["sources"][0][key] = value
            with self.subTest(field=key), self.assertRaisesRegex(derivation.SourceDerivationError, label):
                self.decode(document)

    def test_dependency_cannot_be_reclassified_as_first_party(self):
        document = copy.deepcopy(self.receipt)
        row = next(item for item in document["sources"] if item["repository"] == "spdlog")
        row.update(repository="source", repository_path=row["path"])
        with self.assertRaisesRegex(derivation.SourceDerivationError, "source repository"):
            self.decode(document)

    def test_nonregular_git_modes_reject(self):
        for mode in ("120000", "160000", "040000", 100644):
            document = copy.deepcopy(self.receipt)
            document["sources"][0]["git_mode"] = mode
            with self.subTest(mode=mode), self.assertRaisesRegex(derivation.SourceDerivationError, "Git mode"):
                self.decode(document)

    def test_unknown_repository_and_metadata_fields_reject(self):
        for mutate in (
            lambda row: row.update(extra=True),
            lambda row: row["repositories"].update(extra={}),
            lambda row: row["repositories"]["source"].update(extra=True),
            lambda row: row["sources"][0].update(extra=True),
        ):
            document = copy.deepcopy(self.receipt)
            mutate(document)
            with self.assertRaisesRegex(derivation.SourceDerivationError, "fields differ"):
                self.decode(document)

    def test_repository_url_and_fetch_tag_mutations_reject(self):
        for repository, field, value in (("ramulator", "url", "https://example.invalid/repo.git"),
                ("spdlog", "declared_tag", "latest"), ("softfloat", "producer_path", "../outside")):
            document = copy.deepcopy(self.receipt)
            document["repositories"][repository][field] = value
            with self.subTest(repository=repository), self.assertRaisesRegex(
                    derivation.SourceDerivationError, "derivation repository " + repository):
                self.decode(document)

    def test_duplicate_reordered_or_missing_source_rows_reject(self):
        duplicate = copy.deepcopy(self.receipt)
        duplicate["sources"][1] = copy.deepcopy(duplicate["sources"][0])
        reordered = copy.deepcopy(self.receipt)
        reordered["sources"][0:2] = reversed(reordered["sources"][0:2])
        for document in (duplicate, reordered):
            with self.assertRaisesRegex(derivation.SourceDerivationError, "derived source descriptor"):
                self.decode(document)
        missing = copy.deepcopy(self.receipt)
        missing["sources"].pop()
        with self.assertRaisesRegex(derivation.SourceDerivationError, "derivation source count"):
            self.decode(missing)

    def test_name_and_discovery_digests_are_recomputed(self):
        for key, label in (("source_names_sha256", "derived source names"),
                           ("discovery_helper_sha256", "derived discovery helpers")):
            document = copy.deepcopy(self.receipt)
            document[key] = "0" * 64
            with self.subTest(field=key), self.assertRaisesRegex(derivation.SourceDerivationError, label):
                self.decode(document)

    def test_counts_reject_booleans_and_out_of_bound_values(self):
        for key, value, label in (("schema_version", True, "schema_version"),
                ("source_files", 999.0, "source_files"), ("git_commands", True, "Git commands"),
                ("git_commands", 25001, "Git commands"), ("git_bytes_read", -1, "Git bytes"),
                ("git_bytes_read", 64 * 1024**2 + 1, "Git bytes")):
            document = copy.deepcopy(self.receipt)
            document[key] = value
            with self.subTest(field=key, value=value), self.assertRaisesRegex(
                    derivation.SourceDerivationError, label):
                self.decode(document)

    def test_claims_and_export_limitations_cannot_be_promoted(self):
        for key in (*derivation.FALSE_CLAIMS, "retained_code_executed",
                    "dependency_compilation_provenance_verified"):
            document = copy.deepcopy(self.receipt)
            document[key] = True
            with self.subTest(field=key), self.assertRaisesRegex(derivation.SourceDerivationError, key):
                self.decode(document)
        document = copy.deepcopy(self.receipt)
        document["limitations"] = []
        with self.assertRaisesRegex(derivation.SourceDerivationError, "limitations"):
            self.decode(document)

    def test_ambiguous_and_unbounded_json_rejects(self):
        for body, label in ((b'{"schema_version":1,"schema_version":1}', "duplicate JSON"),
                (b'{"value":NaN}', "nonfinite JSON"),
                (b'{"value":' + b'[' * 70 + b'0' + b']' * 70 + b'}', "JSON nesting")):
            with self.subTest(label=label), self.assertRaisesRegex(derivation.SourceDerivationError, label):
                self.decode(body)

    def test_explicit_receipt_file_and_directory_symlinks_reject(self):
        with tempfile.TemporaryDirectory(prefix="p06-derivation-links-") as temporary:
            root = Path(temporary)
            file_link = root / "receipt.json"
            file_link.symlink_to(RECEIPT)
            directory_link = root / "native"
            directory_link.symlink_to(NATIVE, target_is_directory=True)
            for path in (file_link, directory_link / RECEIPT.name):
                with self.subTest(path=path), self.assertRaisesRegex(
                        derivation.SourceDerivationError, "cannot be read safely"):
                    derivation.load_source_derivation(path, expected_sha256=RECEIPT_SHA256,
                        expected_revision=REVISION, source_inventory=self.manifest,
                        source_inventory_sha256=MANIFEST_SHA256)

    def test_nonregular_and_parent_traversal_receipt_paths_reject(self):
        with tempfile.TemporaryDirectory(prefix="p06-derivation-paths-") as temporary:
            root = Path(temporary)
            fifo = root / "fifo"
            os.mkfifo(fifo)
            for path in (root, fifo, root / ".." / root.name / "receipt.json"):
                with self.subTest(path=path), self.assertRaisesRegex(
                        derivation.SourceDerivationError, "cannot be read safely"):
                    derivation.load_source_derivation(path, expected_sha256=RECEIPT_SHA256,
                        expected_revision=REVISION, source_inventory=self.manifest,
                        source_inventory_sha256=MANIFEST_SHA256)

    def test_receipt_byte_bound_is_enforced_before_json(self):
        with mock.patch.object(derivation, "MAX_RECEIPT_BYTES", 32):
            with self.assertRaisesRegex(derivation.SourceDerivationError, "exceed the limit"):
                self.decode(json_bytes(self.receipt))
            with self.assertRaisesRegex(derivation.SourceDerivationError, "byte limit"):
                derivation.load_source_derivation(RECEIPT, expected_sha256=RECEIPT_SHA256,
                    expected_revision=REVISION, source_inventory=self.manifest,
                    source_inventory_sha256=MANIFEST_SHA256)

    def test_source_body_that_looks_executable_remains_inert(self):
        name = "sim/common/poison.py"
        body = b"raise RuntimeError('retained Python must remain data')\n"
        descriptor = {"path": name, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}
        manifest = copy.deepcopy(self.manifest)
        manifest["sources"] = sorted([*manifest["sources"], descriptor], key=lambda row: row["path"])
        manifest_sha = hashlib.sha256(json_bytes(manifest)).hexdigest()
        document = copy.deepcopy(self.receipt)
        document["sources"].append(dict(descriptor, repository="source", repository_path=name,
            git_mode="100644", git_blob=hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()))
        document["sources"].sort(key=lambda row: row["path"])
        document.update(source_files=len(manifest["sources"]), manifest_sha256=manifest_sha,
            source_names_sha256=hashlib.sha256("".join(row["path"] + "\n"
                for row in manifest["sources"]).encode()).hexdigest(),
            git_commands=document["git_commands"] + 2, git_bytes_read=document["git_bytes_read"] + len(body))
        with ExitStack() as stack:
            for target in ("subprocess.Popen", "os.system", "runpy.run_path", "importlib.util.spec_from_file_location"):
                stack.enter_context(mock.patch(target, side_effect=AssertionError("retained data must not execute")))
            receipt = self.decode(document, source_inventory=manifest, source_inventory_sha256=manifest_sha)
            with zipfile.ZipFile(ORIGINAL) as archive:
                result = derivation.validate_retained_derivation(receipt, checkout=self.checkout,
                    source_body=lambda path: body if path == name else
                        archive.read("managed-preflight/artifacts/source/" + path))
        self.assertEqual(result["source_files_checked"], 1000)
        self.assertIs(result["retained_code_executed"], False)


if __name__ == "__main__":
    unittest.main()
