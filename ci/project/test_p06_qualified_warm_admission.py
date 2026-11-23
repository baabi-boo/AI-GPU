# SPDX-License-Identifier: Apache-2.0
"""Live admission checks with explicitly mocked original-archive replay."""

from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import p06_qualified_warm_admission as admission
import p06_qualified_warm_contract as contract
from test_p06_counter_qualification_admission import AdmissionInputs


ROOT = contract.ROOT


class WarmAdmissionInputs(AdmissionInputs):
    def __init__(self, directory):
        super().__init__(directory)
        self.warm_proof = contract.load_proof(ROOT / contract.SOURCE_PROOF_PATH, contract.SOURCE_PROOF_SHA256)
        self.helpers = admission.reader_sources()
        rows = self.warm_proof["measurement_sources"] + self.helpers + admission.prerequisite_input_rows(self.warm_proof)
        for name in {row["path"] for row in rows}:
            destination = self.source / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)
        self.proof_path = self.source / contract.SOURCE_PROOF_PATH

    def patches(self):
        stack = ExitStack()
        stack.enter_context(mock.patch.object(admission, "_identity", side_effect=self.identity))
        self.diagnostic_replay = stack.enter_context(mock.patch.object(
            admission.prerequisites, "verify_prerequisites", return_value=self.diagnostics))
        self.control_replay = stack.enter_context(mock.patch.object(
            admission.prerequisites, "verify_control_prerequisite", return_value=self.controls))
        return stack

    def admit(self, **overrides):
        return admission.Admission(self.proof_path, contract.SOURCE_PROOF_SHA256,
                                   **dict(self.arguments(), **overrides))


class QualifiedWarmAdmissionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="qualified-warm-admission-")
        self.addCleanup(directory.cleanup)
        self.inputs = WarmAdmissionInputs(directory.name)
        self.patches = self.inputs.patches()
        self.addCleanup(self.patches.close)

    def test_current_projection_and_historical_prerequisites_are_distinct(self):
        value = self.inputs.admit()
        current = value.summary["source_projection"]
        historical = value.summary["historical_prerequisites"]
        self.assertEqual(current["source_proof_sha256"], contract.SOURCE_PROOF_SHA256)
        self.assertEqual(historical["source_proof_sha256"], contract.historical.SOURCE_PROOF_SHA256)
        self.assertNotEqual(current["measurement_sources_sha256"],
                            historical["source_projection"]["measurement_sources_sha256"])
        self.assertEqual(self.inputs.diagnostic_replay.call_args.args[0], self.inputs.proof)
        self.assertEqual(self.inputs.control_replay.call_args.args[0], self.inputs.proof)
        self.assertEqual(value.summary["warm_sampling"], contract.sampling_binding())
        self.assertFalse(value.summary["counter_qualification_passed"])
        self.assertFalse(value.summary["qualified_warm_passed"])
        self.assertEqual(value.summary["native_execution"], "not_run")
        self.assertTrue(all(value.summary[name] is False for name in contract.FALSE_CLAIMS))
        self.assertEqual(value.verify_stable(), admission.stability_summary(
            value.proof, value.helper_sources, value.prerequisite_inputs))

    def test_old_proof_pin_cannot_select_new_route(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            admission.Admission(self.inputs.proof_path, contract.historical.SOURCE_PROOF_SHA256,
                                **self.inputs.arguments())
        self.inputs.diagnostic_replay.assert_not_called()
        self.inputs.control_replay.assert_not_called()

    def test_old_caller_cannot_satisfy_new_measurement_projection(self):
        destination = self.inputs.source / contract.CHANGED_SOURCE
        destination.write_bytes((ROOT / "ci/project/fixtures/p06_counter_preflight_main_v1.cpp").read_bytes())
        with self.assertRaisesRegex(ValueError, "source projection differs"):
            self.inputs.admit()
        self.inputs.diagnostic_replay.assert_not_called()
        self.inputs.control_replay.assert_not_called()

    def test_nonchanged_source_substitution_rejects_before_replay(self):
        destination = self.inputs.source / "sim/common/perf_counter.h"
        destination.write_bytes(destination.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "source projection differs"):
            self.inputs.admit()
        self.inputs.diagnostic_replay.assert_not_called()

    def test_failed_or_other_revision_dependency_admission_rejects(self):
        for name, changed in (("expected_revision", "b" * 40), ("fresh_dependency_build_passed", False)):
            previous = self.inputs.dependency.document[name]
            self.inputs.dependency.document[name] = changed
            with self.subTest(field=name), self.assertRaisesRegex(ValueError, "different source or failed build"):
                self.inputs.admit()
            self.inputs.dependency.document[name] = previous
        with self.assertRaisesRegex(ValueError, "complete live dependency"):
            self.inputs.admit(dependency_admission=self.inputs.dependency.document)
        self.inputs.diagnostic_replay.assert_not_called()

    def test_wrong_archive_pin_and_changed_archive_reject(self):
        with self.assertRaisesRegex(ValueError, "selected original"):
            self.inputs.admit(diagnostic_sha256="0" * 64)
        path = self.inputs.archives["controls"]
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "selected original"):
            self.inputs.admit()
        self.inputs.diagnostic_replay.assert_not_called()

    def test_prerequisite_cannot_claim_qualification_or_include_new_population(self):
        self.inputs.diagnostics["qualified"] = True
        with self.assertRaisesRegex(ValueError, "non-acceptance"):
            self.inputs.admit()
        self.inputs.diagnostics["qualified"] = False
        self.inputs.controls["managed_population_included"] = True
        with self.assertRaisesRegex(ValueError, "prerequisite projection"):
            self.inputs.admit()

    def test_helper_and_prerequisite_changes_reject_before_replay(self):
        for name in ("ci/project/p06_qualified_warm_admission.py", contract.historical.SOURCE_PROOF_PATH):
            target = self.inputs.source / name
            original = target.read_bytes()
            target.write_bytes(original + b"\n")
            with self.subTest(path=name), self.assertRaises(ValueError):
                self.inputs.admit()
            target.write_bytes(original)
        self.inputs.diagnostic_replay.assert_not_called()

    def test_late_measurement_and_original_archive_change_invalidate_admission(self):
        value = self.inputs.admit()
        target = self.inputs.source / contract.CHANGED_SOURCE
        original = target.read_bytes()
        target.write_bytes(original + b"\n")
        with self.assertRaisesRegex(ValueError, "measurement source changed"):
            value.verify_stable()
        target.write_bytes(original)
        target = self.inputs.archives["diagnostics"]
        target.write_bytes(target.read_bytes() + b"late")
        with self.assertRaisesRegex(ValueError, "archive changed"):
            value.verify_stable()

    def test_late_trusted_helper_or_dependency_failure_invalidates_admission(self):
        value = self.inputs.admit()
        rows = deepcopy(value.helper_sources)
        rows[0]["sha256"] = "0" * 64
        with mock.patch.object(admission, "reader_sources", return_value=rows):
            with self.assertRaisesRegex(ValueError, "trusted reader changed"):
                value.verify_stable()
        self.inputs.dependency.verify_stable.side_effect = ValueError("dependency changed after admission")
        with self.assertRaisesRegex(ValueError, "dependency changed"):
            value.verify_stable()

    def test_stability_requires_exact_all_prerequisite_inputs(self):
        value = self.inputs.admit()
        self.assertEqual(len(value.prerequisite_inputs), 3)
        for rows in (value.prerequisite_inputs[:-1], list(reversed(value.prerequisite_inputs))):
            with self.assertRaises(ValueError):
                admission.stability_summary(value.proof, value.helper_sources, rows)


if __name__ == "__main__":
    unittest.main()
