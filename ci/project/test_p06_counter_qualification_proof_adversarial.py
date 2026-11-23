# SPDX-License-Identifier: Apache-2.0
"""Independent public-boundary controls for frozen proof identities."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import p06_counter_qualification_contract as contract


class ProofIdentityAdversarialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.body = (contract.ROOT / contract.SOURCE_PROOF_PATH).read_bytes()
        cls.proof = contract.validate_proof(cls.body)

    def test_count_preserving_counter_reassignment_is_rejected(self):
        remapped_components = deepcopy(self.proof)
        left, right = remapped_components["selectors"][:2]
        left["components"], right["components"] = right["components"], left["components"]
        owners = {component: row["name"]
                  for row in remapped_components["selectors"]
                  for component in row["components"]}
        for row in remapped_components["components"]:
            row["selector"] = owners[row["id"]]

        remapped_coordinates = deepcopy(self.proof)
        left, right = remapped_coordinates["selectors"][:2]
        left["csr"], right["csr"] = right["csr"], left["csr"]
        left["csr_macro"], right["csr_macro"] = right["csr_macro"], left["csr_macro"]

        remapped_provenance = deepcopy(self.proof)
        left = remapped_provenance["selectors"][0]
        right = next(row for row in remapped_provenance["selectors"]
                     if row["source_paths"] != left["source_paths"])
        left["source_paths"], right["source_paths"] = right["source_paths"], left["source_paths"]

        for name, changed in (("consistent component reassignment", remapped_components),
                              ("coordinate reassignment", remapped_coordinates),
                              ("source provenance reassignment", remapped_provenance)):
            with self.subTest(mutation=name):
                self.assertEqual(len(changed["selectors"]), 33)
                self.assertEqual(len(changed["components"]), 40)
                self.assertEqual({row["id"] for row in changed["components"]},
                                 {row["id"] for row in self.proof["components"]})
                self.assertEqual({row["name"] for row in changed["selectors"]},
                                 {row["name"] for row in self.proof["selectors"]})
                with self.assertRaises(ValueError):
                    contract.validate_proof(changed)

    def test_same_premise_population_cannot_exchange_evidence_obligations(self):
        changed = deepcopy(self.proof)
        left, right = changed["premises"][:2]
        left["source_references"], right["source_references"] = (
            right["source_references"], left["source_references"])
        relations = changed["required_fresh_relationships"]
        relations["P01"], relations["P02"] = relations["P02"], relations["P01"]
        self.assertEqual([row["id"] for row in changed["premises"]],
                         [row["id"] for row in self.proof["premises"]])
        self.assertEqual(set(relations), set(self.proof["required_fresh_relationships"]))
        with self.assertRaises(ValueError):
            contract.validate_proof(changed)

    def test_nested_boolean_integer_equality_does_not_change_semantic_identity(self):
        for field in ("core_id", "mpm_class", "initial_value", "component_count"):
            changed = deepcopy(self.proof)
            original = changed["selectors"][0][field]
            replacement = bool(original)
            self.assertEqual(original, replacement)
            self.assertIsNot(type(original), type(replacement))
            changed["selectors"][0][field] = replacement
            with self.subTest(field=field), self.assertRaises(ValueError):
                contract.validate_proof(changed)

    def test_duplicate_nested_keys_cannot_enter_through_the_bytes_boundary(self):
        compact = json.dumps(self.proof, separators=(",", ":")).encode()
        markers = (b'"core_id":0', b'"id":"P01"', b'"path":"VX_config.toml"')
        for marker in markers:
            self.assertIn(marker, compact)
            changed = compact.replace(marker, marker + b"," + marker, 1)
            self.assertEqual(json.loads(changed), self.proof)
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                contract.validate_proof(changed)

    def test_document_key_order_is_semantic_but_file_serialization_is_pinned(self):
        reordered = dict(reversed(tuple(self.proof.items())))
        self.assertEqual(contract.validate_proof(reordered), self.proof)
        body = json.dumps(reordered, separators=(",", ":")).encode()
        self.assertNotEqual(body, self.body)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "proof.json"
            path.write_bytes(body)
            with self.assertRaises(ValueError):
                contract.load_proof(path, contract.SOURCE_PROOF_SHA256)


class ExtendedSourceProjectionAdversarialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proof = contract.validate_proof(
            (contract.ROOT / contract.SOURCE_PROOF_PATH).read_bytes())

    def rows_with_extra(self, extra):
        return sorted(deepcopy(self.proof["measurement_sources"]) + [extra],
                      key=lambda row: row["path"])

    def test_nonmeasurement_sources_still_need_safe_unambiguous_paths(self):
        paths = ("../outside.py", "/absolute.py", "extra//reader.py", "extra/./reader.py",
                 "extra/../reader.py", "extra\\reader.py", "extra/reader.py\x00hidden",
                 "extra/reader.py\n", "extra/reader.py ", "extra/%2e%2e/reader.py",
                 "extra/\u2215reader.py")
        for path in paths:
            rows = self.rows_with_extra({"path": path, "sha256": "1" * 64, "size_bytes": 1})
            with self.subTest(path=path), self.assertRaises(ValueError):
                contract.verify_source_projection(self.proof, rows)

    def test_nonmeasurement_sources_still_need_strict_identity_types(self):
        mutations = (("size_bytes", True), ("size_bytes", 1.0),
                     ("size_bytes", -1), ("size_bytes", contract.MAX_SOURCE_BYTES + 1),
                     ("sha256", "A" * 64), ("sha256", "1" * 63),
                     ("sha256", "1" * 64 + "\n"))
        for field, value in mutations:
            extra = {"path": "extra/reader.py", "sha256": "1" * 64, "size_bytes": 1}
            extra[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                contract.verify_source_projection(self.proof, self.rows_with_extra(extra))

    def test_nonmeasurement_duplicate_identity_is_not_ignored(self):
        extra = {"path": "extra/reader.py", "sha256": "1" * 64, "size_bytes": 1}
        rows = self.rows_with_extra(extra)
        summary = contract.verify_source_projection(self.proof, rows)
        self.assertEqual(summary["measurement_sources_checked"], 69)
        rows.append(deepcopy(extra))
        rows.sort(key=lambda row: row["path"])
        with self.assertRaises(ValueError):
            contract.verify_source_projection(self.proof, rows)


if __name__ == "__main__":
    unittest.main()
