# SPDX-License-Identifier: Apache-2.0
"""Synthetic prerequisite results with real live source/proof stability checks."""

from contextlib import ExitStack
from copy import deepcopy
import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import p06_counter_qualification_admission as admission
import p06_counter_qualification_contract as contract
import p06_dependency_admission as dependency
import p06_dependency_contract as dependency_contract


ROOT = admission.ROOT
REVISION = "a" * 40


class AdmissionInputs:
    """Mock external replay, while keeping the live filesystem checks active."""

    def __init__(self, directory):
        self.root = Path(directory)
        self.source = self.root / "source"
        self.source.mkdir()
        self.proof = contract.load_proof(ROOT / contract.SOURCE_PROOF_PATH,
                                         contract.SOURCE_PROOF_SHA256)
        self.helpers = admission.reader_sources()
        names = {row["path"] for row in self.proof["measurement_sources"] + self.helpers}
        names.add(contract.SOURCE_PROOF_PATH)
        names.add(self.proof["diagnostics"]["public_source_inventory"]["path"])
        for name in names:
            destination = self.source / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)
        self.proof_path = self.source / contract.SOURCE_PROOF_PATH
        self.archives = {}
        for name in ("diagnostics", "controls"):
            path = self.root / (name + ".zip")
            path.write_bytes(("synthetic " + name + " original").encode())
            self.archives[name] = path
        self.real_identity = admission._identity
        self.initial_archive_identities = {path: self.real_identity(path)
                                          for path in self.archives.values()}
        self.dependency = object.__new__(dependency.Admission)
        self.dependency.source = self.source
        self.dependency.document = {
            "contract_id": dependency_contract.CONTRACT_ID,
            "expected_revision": REVISION, "fresh_dependency_build_passed": True,
            "source_manifest": {"sources": [{"name": "ramulator",
                "revision": self.proof["dependency_revision"],
                "tree": dependency_contract.PINS["ramulator"]["tree"],
                "files": [{"path": row["path"], "sha256": row["sha256"],
                           "size_bytes": row["size_bytes"], "oid": row["git_blob"]}
                          for row in self.proof["dependency_sources"]]}]}}
        self.dependency.verification = {"fresh_dependency_build_passed": True}
        self.dependency.verify_stable = mock.Mock(return_value={})
        common = {"schema_version": 1, "contract_id": admission.prerequisites.CONTRACT_ID,
            "outcome": "pass", "native_execution": "not_run", "retained_code_executed": False,
            **dict.fromkeys(contract.FALSE_CLAIMS, False)}
        self.diagnostics = dict(common, scope="pinned-diagnostic-prerequisites-only",
            diagnostic_prerequisites_consistent=True,
            archive=deepcopy(self.proof["diagnostics"]["archive"]),
            source_revision=self.proof["diagnostics"]["source_revision"],
            public_source_inventory_sha256=self.proof["diagnostics"]["public_source_inventory"]["sha256"])
        self.controls = dict(common, scope="pinned-separate-control-prerequisites-only",
            control_prerequisites_consistent=True,
            archive=deepcopy(self.proof["controls"]["archive"]),
            source_revision=self.proof["controls"]["source_revision"],
            projected_measurement_sources=len(self.proof["measurement_sources"]),
            measurement_projection_sha256=contract.digest(self.proof["measurement_sources"]),
            managed_population_included=False,
            positive_pending_contexts=[{"gp": 7}, {"gp": -1}])

    def identity(self, path, **kwargs):
        path = Path(path)
        actual = self.real_identity(path, **kwargs)
        for name, archive in self.archives.items():
            if path == archive and actual == self.initial_archive_identities[path]:
                expected = self.proof[name]["archive"]
                return {"path": str(path), "sha256": expected["sha256"],
                        "size_bytes": expected["size_bytes"]}
        return actual

    def arguments(self):
        return {"source": self.source, "expected_revision": REVISION,
            "dependency_admission": self.dependency,
            "diagnostic_archive": self.archives["diagnostics"],
            "diagnostic_sha256": self.proof["diagnostics"]["archive"]["sha256"],
            "control_archive": self.archives["controls"],
            "control_sha256": self.proof["controls"]["archive"]["sha256"]}

    def patches(self):
        stack = ExitStack()
        stack.enter_context(mock.patch.object(admission, "_identity", side_effect=self.identity))
        self.diagnostic_replay = stack.enter_context(mock.patch.object(
            admission.prerequisites, "verify_prerequisites", return_value=self.diagnostics))
        self.control_replay = stack.enter_context(mock.patch.object(
            admission.prerequisites, "verify_control_prerequisite", return_value=self.controls))
        return stack

    def admit(self, **overrides):
        arguments = dict(self.arguments(), **overrides)
        return admission.Admission(self.proof_path, contract.SOURCE_PROOF_SHA256, **arguments)


class CounterQualificationAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="counter-qualification-admission-")
        self.addCleanup(self.directory.cleanup)
        self.inputs = AdmissionInputs(self.directory.name)
        self.patches = self.inputs.patches()
        self.addCleanup(self.patches.close)

    def test_valid_admission_is_bound_but_does_not_qualify_execution(self):
        value = self.inputs.admit()
        self.assertEqual(value.identity["sha256"], contract.SOURCE_PROOF_SHA256)
        self.assertEqual(value.summary["source_projection"]["measurement_sources_checked"], 69)
        self.assertFalse(value.summary["counter_qualification_passed"])
        self.assertEqual(value.summary["native_execution"], "not_run")
        self.assertTrue(all(value.summary[name] is False for name in contract.FALSE_CLAIMS))
        self.assertEqual(value.summary["controls"]["positive_pending_contexts"][1]["gp"], -1)
        self.assertEqual(value.verify_stable(), admission.stability_summary(
            value.proof, value.helper_sources, value.prerequisite_inputs))
        self.inputs.diagnostic_replay.assert_called_once()
        self.inputs.control_replay.assert_called_once()

    def test_wrong_external_proof_pin_rejects_before_prerequisite_replay(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            admission.Admission(self.inputs.proof_path, "0" * 64, **self.inputs.arguments())
        self.inputs.diagnostic_replay.assert_not_called()
        self.inputs.control_replay.assert_not_called()

    def test_revision_requires_exact_lowercase_git_identity(self):
        for value in (None, True, "master", "A" * 40, "a" * 39):
            with self.subTest(revision=value), self.assertRaisesRegex(ValueError, "exact source revision"):
                self.inputs.admit(expected_revision=value)
        self.inputs.diagnostic_replay.assert_not_called()

    def test_dictionary_cannot_substitute_for_complete_dependency_admission(self):
        with self.assertRaisesRegex(ValueError, "complete live dependency admission"):
            self.inputs.admit(dependency_admission=self.inputs.dependency.document)

    def test_dependency_source_revision_and_build_must_match(self):
        changes = (("expected_revision", "b" * 40), ("fresh_dependency_build_passed", False))
        for key, replacement in changes:
            with self.subTest(field=key):
                previous = self.inputs.dependency.document[key]
                self.inputs.dependency.document[key] = replacement
                with self.assertRaisesRegex(ValueError, "different source or failed build"):
                    self.inputs.admit()
                self.inputs.dependency.document[key] = previous
        self.inputs.dependency.source = self.inputs.root
        with self.assertRaisesRegex(ValueError, "different source or failed build"):
            self.inputs.admit()

    def test_changed_measurement_source_rejects_before_replay(self):
        path = self.inputs.source / self.inputs.proof["measurement_sources"][0]["path"]
        path.write_bytes(path.read_bytes() + b"\nchanged\n")
        with self.assertRaisesRegex(ValueError, "source projection differs"):
            self.inputs.admit()
        self.inputs.diagnostic_replay.assert_not_called()

    def test_changed_helper_source_rejects_before_replay(self):
        path = self.inputs.source / "ci/project/p06_counter_qualification_admission.py"
        path.write_bytes(path.read_bytes() + b"\nchanged\n")
        with self.assertRaisesRegex(ValueError, "executing reader differs"):
            self.inputs.admit()
        self.inputs.diagnostic_replay.assert_not_called()

    def test_proof_symlink_and_hardlink_are_rejected(self):
        link = self.inputs.root / "proof-link.json"
        link.symlink_to(self.inputs.proof_path)
        with self.assertRaisesRegex(ValueError, "without symlinks"):
            admission.Admission(link, contract.SOURCE_PROOF_SHA256, **self.inputs.arguments())
        link.unlink()
        link.hardlink_to(self.inputs.proof_path)
        with self.assertRaisesRegex(ValueError, "unlinked regular"):
            self.inputs.admit()

    def test_archive_pin_and_before_admission_mutation_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "selected original"):
            self.inputs.admit(diagnostic_sha256="f" * 64)
        path = self.inputs.archives["controls"]
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "selected original"):
            self.inputs.admit()
        self.inputs.diagnostic_replay.assert_not_called()

    def test_late_proof_change_invalidates_admission(self):
        value = self.inputs.admit()
        body = self.inputs.proof_path.read_bytes()
        self.inputs.proof_path.write_bytes(body.replace(b"source", b"Source", 1))
        with self.assertRaisesRegex(ValueError, "proof changed"):
            value.verify_stable()

    def test_late_measurement_change_invalidates_admission(self):
        value = self.inputs.admit()
        path = self.inputs.source / self.inputs.proof["measurement_sources"][0]["path"]
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "measurement source changed"):
            value.verify_stable()

    def test_late_helper_change_invalidates_admission(self):
        value = self.inputs.admit()
        path = self.inputs.source / "ci/project/p06_counter_qualification_admission.py"
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "helper or prerequisite input changed"):
            value.verify_stable()

    def test_late_public_inventory_change_invalidates_admission(self):
        value = self.inputs.admit()
        path = self.inputs.source / value.prerequisite_inputs[0]["path"]
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "helper or prerequisite input changed"):
            value.verify_stable()

    def test_late_archive_change_invalidates_admission(self):
        for name in ("diagnostics", "controls"):
            with self.subTest(archive=name):
                value = self.inputs.admit()
                path = self.inputs.archives[name]
                original = path.read_bytes()
                path.write_bytes(original + b"changed")
                with self.assertRaisesRegex(ValueError, "archive changed"):
                    value.verify_stable()
                path.write_bytes(original)

    def test_failed_late_dependency_stability_invalidates_admission(self):
        value = self.inputs.admit()
        self.inputs.dependency.verify_stable.side_effect = ValueError("dependency product changed")
        with self.assertRaisesRegex(ValueError, "dependency product changed"):
            value.verify_stable()

    def test_changed_dependency_component_cannot_be_admitted(self):
        row = self.inputs.dependency.document["source_manifest"]["sources"][0]["files"][0]
        row["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "qualified dependency source"):
            self.inputs.admit()
        self.inputs.diagnostic_replay.assert_not_called()

    def test_prerequisite_replay_failure_is_not_a_fallback(self):
        self.inputs.diagnostic_replay.side_effect = ValueError("missing exact source")
        with self.assertRaisesRegex(ValueError, "missing exact source"):
            self.inputs.admit()
        self.inputs.control_replay.assert_not_called()

    def test_control_claim_cannot_upgrade_prerequisite_scope(self):
        self.inputs.controls["qualified"] = True
        with self.assertRaisesRegex(ValueError, "non-acceptance"):
            self.inputs.admit()

    def test_summary_copies_inputs_and_rejects_wrong_source_projection(self):
        value = self.inputs.admit()
        original = deepcopy(value.summary)
        self.inputs.controls["positive_pending_contexts"][0]["gp"] = 100
        self.assertEqual(value.summary, original)
        source = deepcopy(original["source_projection"])
        source["components"] = 39
        with self.assertRaisesRegex(ValueError, "source projection summary"):
            admission.admission_summary(value.proof, source, original["dependency_projection"],
                                        original["diagnostics"], original["controls"])

    def test_stability_rejects_wrong_prerequisite_descriptor(self):
        value = self.inputs.admit()
        rows = deepcopy(value.prerequisite_inputs)
        rows[0]["sha256"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "input inventory differs"):
            admission.stability_summary(value.proof, value.helper_sources, rows)


class CounterQualificationPathTests(unittest.TestCase):
    def test_identity_rejects_empty_and_symlinked_inputs(self):
        with tempfile.TemporaryDirectory(prefix="qualification-path-") as directory:
            root = Path(directory)
            target = root / "input"
            target.write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "bounded unlinked regular"):
                admission._identity(target)
            target.write_bytes(b"data")
            link = root / "link"
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "without symlinks"):
                admission._identity(link)

    def test_identity_reads_real_regular_bytes(self):
        with tempfile.TemporaryDirectory(prefix="qualification-path-") as directory:
            target = Path(directory) / "input"
            target.write_bytes(b"data")
            self.assertEqual(admission._identity(target), {"path": str(target),
                "sha256": hashlib.sha256(b"data").hexdigest(), "size_bytes": 4})


if __name__ == "__main__":
    unittest.main()
