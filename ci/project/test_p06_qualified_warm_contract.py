# SPDX-License-Identifier: Apache-2.0
"""Fixed warm projection and sampling controls; no native execution."""

from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest

import p06_qualified_warm_contract as contract


ROOT = contract.ROOT


class QualifiedWarmContractTests(unittest.TestCase):
    def setUp(self):
        self.body = (ROOT / contract.SOURCE_PROOF_PATH).read_bytes()
        self.proof = contract.validate_proof(self.body)

    def test_exact_proof_joins_original_and_one_native_source_change(self):
        self.assertEqual(hashlib.sha256(self.body).hexdigest(), contract.SOURCE_PROOF_SHA256)
        original = contract.base_proof()
        old = {row["path"]: row for row in original["measurement_sources"]}
        new = {row["path"]: row for row in self.proof["measurement_sources"]}
        self.assertEqual(set(old), set(new))
        self.assertEqual([name for name in old if old[name] != new[name]], [contract.CHANGED_SOURCE])
        self.assertEqual(len(new), 69)
        self.assertEqual(self.proof["premises"], list(contract.PREMISE_IDS))

    def test_current_source_projection_passes_but_historical_one_rejects(self):
        rows = []
        for expected in self.proof["measurement_sources"]:
            body = (ROOT / expected["path"]).read_bytes()
            rows.append({"path": expected["path"], "sha256": hashlib.sha256(body).hexdigest(),
                         "size_bytes": len(body)})
        result = contract.verify_source_projection(self.proof, rows)
        self.assertEqual(result["measurement_sources_checked"], 69)
        with self.assertRaisesRegex(ValueError, "projection differs"):
            contract.historical.verify_source_projection(contract.base_proof(), rows)

    def test_source_substitution_omission_and_duplicates_reject(self):
        for change in ("changed", "unchanged", "omitted", "duplicate", "unsorted"):
            rows = deepcopy(self.proof["measurement_sources"])
            if change in ("changed", "unchanged"):
                row = next(row for row in rows if (row["path"] == contract.CHANGED_SOURCE) == (change == "changed"))
                row["sha256"] = "0" * 64
            elif change == "omitted":
                rows.pop()
            elif change == "duplicate":
                rows.append(rows[-1])
            else:
                rows.reverse()
            with self.subTest(change=change), self.assertRaises(ValueError):
                contract.verify_source_projection(self.proof, rows)

    def test_sampling_has_exact_population_identity_phase_and_alternating_order(self):
        plan = contract.process_plan()
        self.assertEqual(len(plan), 24)
        self.assertEqual(len({row["id"] for row in plan}), 24)
        self.assertEqual(sum(row["phase"] == "warmup" for row in plan), 4)
        self.assertEqual(sum(row["phase"] == "measured" for row in plan), 20)
        for format_index, fmt in enumerate(("fp16", "bf16")):
            for pair in range(6):
                rows = plan[format_index * 12 + pair * 2:format_index * 12 + pair * 2 + 2]
                expected = list(contract.warm.POLICIES)
                if pair % 2:
                    expected.reverse()
                self.assertEqual([row["policy"] for row in rows], expected)
                for row in rows:
                    self.assertEqual(row["format"], fmt)
                    self.assertEqual(row["pair_index"], pair)
                    self.assertEqual(row["sample_id"], row["id"])
                    self.assertEqual(row["phase"], "warmup" if pair == 0 else "measured")
        self.assertEqual(contract.COMPLETE_COUNTS["launches"], 792)
        self.assertEqual(contract.COMPLETE_COUNTS["checked_words"], 25344)

    def test_semantic_changes_cannot_reselect_source_sampling_or_claims(self):
        for field in ("source_changes", "sampling", "processes", "claims", "premises", "extra"):
            value = deepcopy(self.proof)
            if field == "source_changes":
                value[field][0]["after"]["sha256"] = "0" * 64
            elif field == "sampling":
                value[field]["measured_pairs"] = 4
            elif field == "processes":
                value[field].reverse()
            elif field == "claims":
                value[field]["qualified"] = True
            elif field == "premises":
                value[field].pop()
            else:
                value[field] = "untrusted route selector"
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "semantic contract"):
                contract.validate_proof(value)

    def test_raw_byte_changes_are_not_accepted_as_same_proof(self):
        for value in (self.body + b" ", self.body[:-1], self.body.replace(b'"schema_version": 1', b'"schema_version": true')):
            with self.assertRaisesRegex(ValueError, "byte identity"):
                contract.validate_proof(value)

    def test_selected_pin_and_filesystem_identity_are_required(self):
        with tempfile.TemporaryDirectory(prefix="qualified-warm-proof-") as directory:
            path = Path(directory) / "proof.json"
            path.write_bytes(self.body)
            self.assertEqual(contract.load_proof(path, contract.SOURCE_PROOF_SHA256), self.proof)
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                contract.load_proof(path, contract.historical.SOURCE_PROOF_SHA256)
            alias = path.with_name("alias.json")
            alias.symlink_to(path)
            with self.assertRaisesRegex(ValueError, "symlinks"):
                contract.load_proof(alias, contract.SOURCE_PROOF_SHA256)
            alias.unlink()
            alias.hardlink_to(path)
            with self.assertRaisesRegex(ValueError, "unlinked regular"):
                contract.load_proof(path, contract.SOURCE_PROOF_SHA256)

    def test_returned_data_is_independent_and_nonaccepting(self):
        self.proof["measurement_sources"][0]["sha256"] = "0" * 64
        fresh = contract.validate_proof(self.body)
        self.assertNotEqual(fresh["measurement_sources"][0]["sha256"], "0" * 64)
        self.assertTrue(all(value is False for value in fresh["claims"].values()))
        self.assertEqual(contract.contract()["warm_sampling"], contract.sampling_binding())


if __name__ == "__main__":
    unittest.main()
