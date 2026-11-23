# SPDX-License-Identifier: Apache-2.0
"""Adversarial controls for the fixed counter proof and source projection."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

import p06_counter_qualification_contract as contract


class FrozenProofTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.body = (contract.ROOT / contract.SOURCE_PROOF_PATH).read_bytes()
        cls.proof = contract.validate_proof(cls.body)

    def test_reviewed_proof_has_complete_disjoint_counter_populations(self):
        proof = contract.validate_proof(self.body)
        names = {row["name"] for row in proof["selectors"]}
        self.assertEqual(len(names), 33)
        self.assertEqual(len(proof["components"]), 40)
        self.assertFalse(names & {row["name"] for row in proof["unavailable_selectors"]})
        self.assertEqual(sum(len(row["components"]) == 2 for row in proof["selectors"]), 7)
        self.assertNotIn("ProcessorImpl::perf_mem_pending_reads_",
                         {row["id"] for row in proof["components"]})

    def test_actual_measurement_bytes_match_reviewed_projection(self):
        rows = []
        for expected in self.proof["measurement_sources"]:
            body = (contract.ROOT / expected["path"]).read_bytes()
            rows.append({"path": expected["path"], "sha256": hashlib.sha256(body).hexdigest(),
                         "size_bytes": len(body)})
        summary = contract.verify_source_projection(self.proof, rows)
        self.assertEqual(summary["measurement_sources_checked"], 69)
        self.assertEqual(summary["premises"], list(contract.PREMISE_IDS))

    def test_only_the_reviewed_accessor_sources_differ_from_old_proof(self):
        rows = self.proof["source_projection_changes"]
        self.assertEqual([row["path"] for row in rows], [
            "sim/simx/processor.cpp", "sim/simx/processor.h", "sim/simx/processor_impl.h"])
        measured = {row["path"]: row for row in self.proof["measurement_sources"]}
        for row in rows:
            self.assertNotEqual(row["previous_sha256"], row["sha256"])
            self.assertEqual(row["sha256"], measured[row["path"]]["sha256"])

    def test_proof_cannot_be_changed_by_rehashing_an_internally_consistent_document(self):
        mutations = []
        omitted = deepcopy(self.proof)
        omitted["components"].pop()
        mutations.append(omitted)
        duplicate = deepcopy(self.proof)
        duplicate["components"][1] = deepcopy(duplicate["components"][0])
        mutations.append(duplicate)
        bank = deepcopy(self.proof)
        bank["selectors"][16]["components"][1] = bank["selectors"][16]["components"][0]
        mutations.append(bank)
        premise = deepcopy(self.proof)
        premise["premises"][8]["source_references"] = []
        mutations.append(premise)
        control = deepcopy(self.proof)
        control["controls"]["native_report_sha256"] = "a" * 64
        mutations.append(control)
        claim = deepcopy(self.proof)
        claim["claims"]["qualified"] = True
        mutations.append(claim)
        for value in mutations:
            encoded = json.dumps(value, sort_keys=True).encode()
            self.assertNotEqual(hashlib.sha256(encoded).hexdigest(), contract.SOURCE_PROOF_SHA256)
            with self.subTest(fields=list(value)), self.assertRaises(ValueError):
                contract.validate_proof(value)
            with self.subTest(encoded=True), self.assertRaises(ValueError):
                contract.validate_proof(encoded)

    def test_wrong_version_types_unknown_fields_and_premise_booleans_reject(self):
        for field, value in (("schema_version", True), ("schema_version", 1.0),
                             ("premises_passed", True), ("premises", dict.fromkeys(contract.PREMISE_IDS, True))):
            altered = deepcopy(self.proof)
            altered[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                contract.validate_proof(altered)

    def test_non_json_containers_cannot_mimic_the_canonical_document(self):
        altered = deepcopy(self.proof)
        altered["selectors"] = tuple(altered["selectors"])
        with self.assertRaises(ValueError):
            contract.validate_proof(altered)

    def test_returned_proof_is_not_mutable_shared_trust(self):
        first = contract.validate_proof(self.body)
        first["components"].clear()
        self.assertEqual(len(contract.validate_proof(self.body)["components"]), 40)

    def test_duplicate_fields_and_unbounded_json_fail_closed(self):
        samples = [b'{"schema_version":1,"schema_version":1}', b'{"x":NaN}',
                   b'{"x":1.0}', b'{"x":18446744073709551616}',
                   b'{"x":' + b'9' * 10000 + b'}', b'[' * 100 + b']' * 100,
                   b' ' * (contract.MAX_PROOF_BYTES + 1), b'\xff', b'']
        for body in samples:
            with self.subTest(length=len(body)), self.assertRaises(ValueError):
                contract.validate_proof(body)

    def test_source_or_control_claims_are_not_qualification(self):
        self.assertTrue(all(self.proof["claims"][name] is False for name in contract.FALSE_CLAIMS))
        current = contract.contract()
        self.assertEqual(current["result_scope"], "complete-fresh-four-process-preflight")
        self.assertEqual(current["measurement_contract_sha256"], contract.WARM_CONTRACT_SHA256)
        self.assertNotIn("qualified", current)


class SourceProjectionTests(unittest.TestCase):
    def setUp(self):
        self.proof = contract.validate_proof((contract.ROOT / contract.SOURCE_PROOF_PATH).read_bytes())
        self.rows = deepcopy(self.proof["measurement_sources"])

    def test_incomplete_projection_rejects_every_missing_component_source(self):
        for index, row in enumerate(self.rows):
            changed = self.rows[:index] + self.rows[index + 1:]
            with self.subTest(path=row["path"]), self.assertRaisesRegex(ValueError, "projection differs"):
                contract.verify_source_projection(self.proof, changed)

    def test_changed_source_hash_and_size_reject_even_with_same_inventory(self):
        for field, value in (("sha256", "0" * 64), ("size_bytes", 0)):
            changed = deepcopy(self.rows)
            changed[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                contract.verify_source_projection(self.proof, changed)

    def test_reverting_new_accessor_to_old_hash_is_not_equivalent(self):
        for change in self.proof["source_projection_changes"]:
            rows = deepcopy(self.rows)
            next(row for row in rows if row["path"] == change["path"])["sha256"] = change["previous_sha256"]
            with self.subTest(path=change["path"]), self.assertRaises(ValueError):
                contract.verify_source_projection(self.proof, rows)

    def test_complete_inventory_may_include_other_bound_build_sources(self):
        rows = sorted(self.rows + [{"path": "ci/project/other_reader.py", "sha256": "1" * 64,
                                   "size_bytes": 1}], key=lambda row: row["path"])
        self.assertEqual(contract.verify_source_projection(self.proof, rows)["measurement_sources_checked"], 69)

    def test_unknown_unsafe_or_duplicate_descriptor_fields_reject(self):
        mutations = []
        duplicate = deepcopy(self.rows)
        duplicate.insert(0, deepcopy(duplicate[0]))
        mutations.append(duplicate)
        extra = deepcopy(self.rows)
        extra[0]["trusted"] = True
        mutations.append(extra)
        for path in ("../sim/core.cpp", "/absolute.cpp", "sim//core.cpp", "sim/./core.cpp", "sim/../core.cpp"):
            changed = deepcopy(self.rows)
            changed[0]["path"] = path
            mutations.append(changed)
        for changed in mutations:
            with self.subTest(first=changed[0]), self.assertRaises(ValueError):
                contract.verify_source_projection(self.proof, changed)

    def test_wrong_identity_types_and_descriptor_order_reject(self):
        for field, value in (("size_bytes", True), ("size_bytes", 1.0),
                             ("sha256", "A" * 64), ("path", 1)):
            changed = deepcopy(self.rows)
            changed[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                contract.verify_source_projection(self.proof, changed)
        with self.assertRaises(ValueError):
            contract.verify_source_projection(self.proof, list(reversed(self.rows)))


class ProofFileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "proof.json"
        self.path.write_bytes((contract.ROOT / contract.SOURCE_PROOF_PATH).read_bytes())

    def test_exact_external_pin_and_regular_original_load(self):
        proof = contract.load_proof(self.path, contract.SOURCE_PROOF_SHA256)
        self.assertEqual(proof["contract_id"], contract.PROOF_CONTRACT_ID)

    def test_missing_wrong_or_self_selected_new_digest_rejects(self):
        for pin in (None, "", "a" * 64, 1, True):
            with self.subTest(pin=pin), self.assertRaises(ValueError):
                contract.load_proof(self.path, pin)
        self.path.write_bytes(b'{}\n')
        changed_pin = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            contract.load_proof(self.path, changed_pin)

    def test_direct_symlink_and_symlink_parent_reject(self):
        link = self.root / "link.json"
        link.symlink_to(self.path)
        parent_link = self.root / "linked"
        parent_link.symlink_to(self.root, target_is_directory=True)
        for path in (link, parent_link / self.path.name):
            with self.subTest(path=path), self.assertRaises(ValueError):
                contract.load_proof(path, contract.SOURCE_PROOF_SHA256)

    def test_hardlinked_proof_rejects(self):
        linked = self.root / "hardlink.json"
        os.link(self.path, linked)
        with self.assertRaises(ValueError):
            contract.load_proof(self.path, contract.SOURCE_PROOF_SHA256)

    def test_missing_changed_empty_or_oversized_proof_rejects(self):
        for body in (b'', b'{}', b' ' * (contract.MAX_PROOF_BYTES + 1)):
            self.path.write_bytes(body)
            with self.subTest(length=len(body)), self.assertRaises(ValueError):
                contract.load_proof(self.path, contract.SOURCE_PROOF_SHA256)
        self.path.unlink()
        with self.assertRaises(OSError):
            contract.load_proof(self.path, contract.SOURCE_PROOF_SHA256)


if __name__ == "__main__":
    unittest.main()
