# SPDX-License-Identifier: Apache-2.0
"""Pinned original and adversarial prerequisite joins; no native execution."""

from contextlib import ExitStack
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import p06_counter_qualification_contract as contract
import p06_counter_qualification_prerequisites as prerequisites


ROOT = prerequisites.ROOT
DIAGNOSTIC = ROOT / "docs/project/evidence/p06-counter-diagnostics/native/run-45034575685-attempt1.zip"


class DiagnosticPrerequisiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proof = contract.load_proof(ROOT / contract.SOURCE_PROOF_PATH, contract.SOURCE_PROOF_SHA256)
        expected = cls.proof["diagnostics"]
        cls.model = prerequisites.model_reader.replay_archive(DIAGNOSTIC, expected["archive"]["sha256"],
            expected_revision=expected["source_revision"])
        cls.public = prerequisites.public_reader.replay_archive(DIAGNOSTIC, expected["archive"]["sha256"],
            expected_revision=expected["source_revision"],
            source_inventory=ROOT / expected["public_source_inventory"]["path"],
            source_inventory_sha256=expected["public_source_inventory"]["sha256"])

    def run_join(self, *, proof=None, model=None, public=None):
        with mock.patch.object(prerequisites.model_reader, "replay_archive",
                               return_value=deepcopy(self.model if model is None else model)), \
             mock.patch.object(prerequisites.public_reader, "replay_archive",
                               return_value=deepcopy(self.public if public is None else public)):
            return prerequisites.verify_prerequisites(self.proof if proof is None else proof,
                diagnostic_archive=DIAGNOSTIC, diagnostic_sha256=self.proof["diagnostics"]["archive"]["sha256"])

    def test_actual_original_is_replayed_without_execution_or_extraction(self):
        with ExitStack() as stack:
            for target in ("subprocess.run", "subprocess.Popen", "os.system", "socket.socket",
                           "zipfile.ZipFile.extract", "zipfile.ZipFile.extractall"):
                stack.enter_context(mock.patch(target, side_effect=AssertionError("prohibited replay effect")))
            result = prerequisites.verify_prerequisites(self.proof, diagnostic_archive=DIAGNOSTIC,
                diagnostic_sha256=self.proof["diagnostics"]["archive"]["sha256"])
        self.assertEqual(result["coverage"]["public_terminal_queries"], 231)
        self.assertEqual(result["coverage"]["model_cells"], 7)
        self.assertEqual(result["coverage"]["public_cells"], 6)
        self.assertEqual(result["projection"]["historical_source_files"], 321)
        self.assertEqual(result["projection"]["diagnostic_sources"], 7)
        self.assertEqual(result["native_execution"], "not_run")
        for name in contract.FALSE_CLAIMS:
            self.assertIs(result[name], False)

    def test_wrong_external_digest_rejects_before_either_reader(self):
        with mock.patch.object(prerequisites.model_reader, "replay_archive") as model, \
             mock.patch.object(prerequisites.public_reader, "replay_archive") as public:
            for value in ("0" * 64, None, True, b"0" * 64):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    prerequisites.verify_prerequisites(self.proof, diagnostic_archive=DIAGNOSTIC,
                                                        diagnostic_sha256=value)
        model.assert_not_called()
        public.assert_not_called()

    def test_changed_trusted_archive_helper_rejects_before_either_reader(self):
        original = Path.read_bytes
        helper = ROOT / prerequisites.model_reader.trusted.ARCHIVE_READER_PATH

        def changed(path):
            body = original(path)
            return body + b"\n# changed trusted helper\n" if path == helper else body

        with mock.patch.object(Path, "read_bytes", changed), \
             mock.patch.object(prerequisites.model_reader, "replay_archive") as model, \
             mock.patch.object(prerequisites.public_reader, "replay_archive") as public:
            with self.assertRaisesRegex(ValueError, "trusted archive helper"):
                prerequisites.verify_prerequisites(self.proof, diagnostic_archive=DIAGNOSTIC,
                    diagnostic_sha256=self.proof["diagnostics"]["archive"]["sha256"])
        model.assert_not_called()
        public.assert_not_called()

    def test_changed_original_bytes_reject_even_with_same_filename(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / DIAGNOSTIC.name
            path.write_bytes(DIAGNOSTIC.read_bytes() + b"changed-original")
            with self.assertRaises(ValueError):
                prerequisites.verify_prerequisites(self.proof, diagnostic_archive=path,
                    diagnostic_sha256=self.proof["diagnostics"]["archive"]["sha256"])

    def test_changed_proof_is_not_authority_for_new_sources(self):
        proof = deepcopy(self.proof)
        proof["diagnostic_projection"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "reviewed semantic contract"):
            self.run_join(proof=proof)

    def test_wrong_reader_scope_or_claim_cannot_be_promoted(self):
        cases = [("native_execution", "run"), ("qualified", True), ("retained_code_executed", True),
                 ("source_revision", "0" * 40), ("scope", "qualified"), ("cells_checked", True)]
        for key, value in cases:
            with self.subTest(key=key):
                public = deepcopy(self.public)
                public[key] = value
                with self.assertRaises(ValueError):
                    self.run_join(public=public)

    def test_public_manifest_selection_is_required(self):
        public = deepcopy(self.public)
        public["source_inventory_expectation"]["source"] = "original-inventory"
        with self.assertRaisesRegex(ValueError, "explicit public source inventory"):
            self.run_join(public=public)

    def test_omitted_or_repeated_model_control_fails(self):
        for repeated in (False, True):
            model = deepcopy(self.model)
            if repeated:
                model["variants"][1]["cells"][-1] = model["variants"][1]["cells"][-2]
            else:
                model["variants"][1]["cells"].pop()
            with self.subTest(repeated=repeated), self.assertRaises(ValueError):
                self.run_join(model=model)

    def test_same_component_count_does_not_excuse_duplicate_selector(self):
        model = deepcopy(self.model)
        model["variants"][1]["cells"][0]["observations"]["transport_selectors"][-1] = "cycles"
        with self.assertRaisesRegex(ValueError, "transport_selectors"):
            self.run_join(model=model)

    def test_missing_public_suppression_or_terminal_vector_fails(self):
        for field in ("suppressed_requests", "terminal_snapshots"):
            public = deepcopy(self.public)
            public["public"]["cells"][1]["observations"][field] = 0 if field == "suppressed_requests" else []
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.run_join(public=public)

    def test_rehashed_source_projection_does_not_match_original(self):
        public = deepcopy(self.public)
        row = next(row for row in public["archive_read"]["read_files"]
                   if row["path"] == "public-counters/artifacts/source/sim/simx/processor.cpp")
        row["sha256"] = hashlib.sha256(b"replacement-getter").hexdigest()
        with self.assertRaisesRegex(ValueError, "common source|production projection"):
            self.run_join(public=public)

    def test_source_join_independently_rejects_a_false_reviewed_delta(self):
        proof = deepcopy(self.proof)
        proof["source_projection_changes"][0]["previous_sha256"] = "0" * 64
        with mock.patch.object(contract, "validate_proof", side_effect=lambda value: value):
            with self.assertRaisesRegex(ValueError, "previous getter"):
                self.run_join(proof=proof)

    def test_missing_source_is_not_filled_from_live_checkout(self):
        public = deepcopy(self.public)
        public["archive_read"]["read_files"] = [row for row in public["archive_read"]["read_files"]
            if row["path"] != "public-counters/artifacts/source/sim/simx/processor.cpp"]
        with self.assertRaisesRegex(ValueError, "checked source count"):
            self.run_join(public=public)


def synthetic_control_result(proof):
    """Invent a control-reader result for join fault injection, not native proof."""
    controls = proof["controls"]
    rows = [dict(row, path="native-lifetime/artifacts/source/" + row["path"])
            for row in proof["measurement_sources"]]
    rows.append(dict(controls["probe_source"], path="pending-probe/inputs/" + controls["probe_source"]["path"]))
    common = {"outcome": "pass", "managed_population_included": False,
              "native_execution": "not_run", "retained_code_executed": False,
              **dict.fromkeys(contract.FALSE_CLAIMS, False)}
    return {"schema_version": 1, "contract_id": prerequisites.control_reader.CONTRACT_ID,
            "outcome": "pass", "retained_consistency": True, "source_revision": controls["source_revision"],
            "native_execution": "not_run", "retained_code_executed": False,
            **dict.fromkeys(contract.FALSE_CLAIMS, False),
            "archive_read": {"archive": {key: controls["archive"][key] for key in ("sha256", "size_bytes")},
                             "data_files": controls["archive"]["members"], "read_files": rows},
            "managed_counts": deepcopy(prerequisites.control_reader.producer.COMPLETE_COUNTS),
            "native_review": {"retained_source_files_checked": len(proof["measurement_sources"])},
            "pending_probe": {**common, "report_sha256": controls["probe_report_sha256"],
                "processes": 2, "contexts": 2, "commands_checked": 5,
                "always_zero_rejection": "FAILED pending_reads native_probe: pending getter did not observe an outstanding read",
                "positive_pending_contexts": [{"gp": gp, "checked_gp": gp, "max_pending": 1,
                    "pending_final": 0, "positive_samples": 23, "readonly_checks": 137,
                    "checked_reset_delta": 1, "stepped_reset_delta": 1, "steps": 135} for gp in (7, -1)]},
            "dependency_substitution": {**common, "report_sha256": controls["substitution_report_sha256"],
                "rejection": "loaded library libramulator-vortex.so: differs from the fixed contract",
                "control_counts": {"processes": 1, "launches": 33, "checked_words": 1056, "snapshots": 4,
                    "available_queries": 132, "half_replies": 264, "cache_flush_reads": 33,
                    "dcr_reads": 297, "unavailable_rows": 48}}}


class ControlPrerequisiteTests(unittest.TestCase):
    def setUp(self):
        self.proof = contract.load_proof(ROOT / contract.SOURCE_PROOF_PATH, contract.SOURCE_PROOF_SHA256)
        self.result = synthetic_control_result(self.proof)

    def run_join(self):
        with mock.patch.object(prerequisites.control_reader, "replay_archive", return_value=self.result) as reader:
            result = prerequisites.verify_control_prerequisite(self.proof,
                archive=Path("/caller-selected/control.zip"), sha256=self.proof["controls"]["archive"]["sha256"])
        self.assertEqual(reader.call_count, 1)
        self.assertEqual(reader.call_args.kwargs["expected_probe_report_sha256"],
                         self.proof["controls"]["probe_report_sha256"])
        return result

    def test_join_keeps_control_population_separate(self):
        result = self.run_join()
        self.assertFalse(result["managed_population_included"])
        self.assertEqual(result["projected_measurement_sources"], len(self.proof["measurement_sources"]))
        self.assertEqual(result["positive_pending_contexts"][1]["gp"], -1)
        self.assertIs(result["qualified"], False)

    def test_wrong_control_pin_fails_before_replay(self):
        with mock.patch.object(prerequisites.control_reader, "replay_archive") as reader:
            with self.assertRaises(ValueError):
                prerequisites.verify_control_prerequisite(self.proof,
                    archive=Path("/caller-selected/control.zip"), sha256="0" * 64)
        reader.assert_not_called()

    def test_zero_accessor_substitution_fails(self):
        self.result["pending_probe"]["positive_pending_contexts"][0]["max_pending"] = 0
        with self.assertRaisesRegex(ValueError, "positive-pending"):
            self.run_join()

    def test_unrelated_negative_failure_is_not_the_control(self):
        self.result["pending_probe"]["always_zero_rejection"] = "process crashed"
        with self.assertRaisesRegex(ValueError, "always_zero_rejection"):
            self.run_join()

    def test_changed_native_accessor_bytes_fail_projection(self):
        row = next(row for row in self.result["archive_read"]["read_files"]
                   if row["path"] == "native-lifetime/artifacts/source/sim/simx/processor.cpp")
        row["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "control/measurement source"):
            self.run_join()

    def test_changed_actual_probe_source_fails(self):
        self.result["archive_read"]["read_files"][-1]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "actual accessor probe source"):
            self.run_join()

    def test_substitution_without_expected_rejection_fails(self):
        self.result["dependency_substitution"]["rejection"] = "different failure"
        with self.assertRaisesRegex(ValueError, "exact provenance rejection"):
            self.run_join()


class DependencyProjectionTests(unittest.TestCase):
    def setUp(self):
        self.proof = contract.load_proof(ROOT / contract.SOURCE_PROOF_PATH, contract.SOURCE_PROOF_SHA256)
        self.document = {"contract_id": prerequisites.dependencies.CONTRACT_ID,
            "source_manifest": {"sources": [{"name": "ramulator", "revision": self.proof["dependency_revision"],
                "tree": prerequisites.dependencies.PINS["ramulator"]["tree"],
                "files": [{"path": row["path"], "sha256": row["sha256"], "size_bytes": row["size_bytes"],
                           "oid": row["git_blob"], "mode": "100644"} for row in self.proof["dependency_sources"]]}]}}

    def test_all_twenty_one_sources_join(self):
        result = prerequisites.verify_dependency_projection(self.proof, self.document)
        self.assertEqual(result["source_files"], 21)
        self.assertNotIn("qualified", result)

    def test_missing_repeated_or_changed_finalizer_source_fails(self):
        for mutation in ("missing", "repeated", "sha256", "oid", "size_bytes"):
            document = deepcopy(self.document)
            files = document["source_manifest"]["sources"][0]["files"]
            if mutation == "missing":
                files.pop()
            elif mutation == "repeated":
                files.append(files[0])
            else:
                files[0][mutation] = 0 if mutation == "size_bytes" else "0" * len(files[0][mutation])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                prerequisites.verify_dependency_projection(self.proof, document)

    def test_wrong_revision_or_tree_fails(self):
        for key in ("revision", "tree"):
            document = deepcopy(self.document)
            document["source_manifest"]["sources"][0][key] = "0" * 40
            with self.subTest(key=key), self.assertRaises(ValueError):
                prerequisites.verify_dependency_projection(self.proof, document)


if __name__ == "__main__":
    unittest.main()
