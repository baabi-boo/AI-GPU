# SPDX-License-Identifier: Apache-2.0
"""Admit the fixed warm source extension and unchanged original prerequisites."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

import p06_counter_qualification_admission as historical
import p06_counter_qualification_prerequisites as prerequisites
import p06_dependency_admission as dependency
import p06_qualified_warm_contract as qualification


ROOT = qualification.ROOT
CONTRACT_ID = qualification.CONTRACT_ID
SCOPE = qualification.SCOPE
SOURCE_FILES = qualification.SOURCE_FILES
LIMITATIONS = qualification.LIMITATIONS
contract = qualification.contract
contract_hash = qualification.contract_hash
require = qualification.require
_identity = historical._identity
_relative_identity = historical._relative_identity


def reader_sources():
    rows = {row["path"]: row for row in historical.reader_sources()}
    for module in (qualification, sys.modules[__name__]):
        path = ROOT / "ci/project" / (module.__name__ + ".py")
        require(Path(module.__file__).resolve(strict=True) == path,
                "qualified warm admission helper is outside the trusted checkout")
        name = path.relative_to(ROOT).as_posix()
        rows[name] = _relative_identity(ROOT, name)
    reference_pins = {**qualification.warm._SOURCE_HASHES,
                      qualification.warm.MANIFEST_PATH: qualification.WARM_CONTRACT_SHA256}
    for name, expected_sha256 in reference_pins.items():
        identity = _relative_identity(ROOT, name)
        require(identity["sha256"] == expected_sha256,
                "qualified warm reference input changed: " + name)
        rows[name] = identity
    return [rows[name] for name in sorted(rows)]


def prerequisite_input_rows(proof):
    proof = qualification.validate_proof(proof)
    original = qualification.base_proof()
    return sorted([
        deepcopy(proof["base_source_proof"]),
        deepcopy(original["diagnostics"]["public_source_inventory"]),
        {"path": qualification.SOURCE_PROOF_PATH, "sha256": qualification.SOURCE_PROOF_SHA256,
         "size_bytes": qualification.SOURCE_PROOF_BYTES},
    ], key=lambda row: row["path"])


def admission_summary(proof, source_projection, dependency_projection, diagnostics, controls):
    """Compose separately verified historical prerequisites and current source projection."""
    proof = qualification.validate_proof(proof)
    original = qualification.base_proof()
    require(source_projection == qualification.verify_source_projection(proof, proof["measurement_sources"]),
            "qualified warm source projection summary differs")
    historical_projection = qualification.historical.verify_source_projection(
        original, original["measurement_sources"])
    old = historical.admission_summary(original, historical_projection,
                                      dependency_projection, diagnostics, controls)
    return {"schema_version": 1, "contract_id": CONTRACT_ID,
        "scope": "prelaunch-qualified-warm-source-prerequisites",
        "source_proof_sha256": qualification.SOURCE_PROOF_SHA256,
        "qualification_contract_sha256": contract_hash(),
        "source_projection": deepcopy(source_projection),
        "dependency_projection": deepcopy(dependency_projection),
        "historical_prerequisites": old,
        "warm_sampling": qualification.sampling_binding(),
        "native_execution": "not_run", "counter_qualification_passed": False,
        "qualified_warm_passed": False,
        **dict.fromkeys(qualification.FALSE_CLAIMS, False)}


def stability_summary(proof, helper_sources, prerequisite_inputs):
    proof = qualification.validate_proof(proof)
    original = qualification.base_proof()
    qualification.historical._source_rows(helper_sources)
    qualification.historical._source_rows(prerequisite_inputs)
    require(prerequisite_inputs == prerequisite_input_rows(proof),
            "qualified warm prerequisite input inventory differs")
    return {"proof_sha256": qualification.SOURCE_PROOF_SHA256,
        "historical_proof_sha256": qualification.historical.SOURCE_PROOF_SHA256,
        "measurement_sources_sha256": qualification.digest(proof["measurement_sources"]),
        "helper_sources_sha256": qualification.digest(helper_sources),
        "prerequisite_inputs_sha256": qualification.digest(prerequisite_inputs),
        "warm_sampling_sha256": qualification.digest(qualification.sampling_binding()),
        "diagnostic_archive_sha256": original["diagnostics"]["archive"]["sha256"],
        "control_archive_sha256": original["controls"]["archive"]["sha256"]}


class Admission:
    def __init__(self, path, expected_sha256, *, source, expected_revision,
                 dependency_admission, diagnostic_archive, diagnostic_sha256,
                 control_archive, control_sha256):
        require(type(expected_revision) is str and historical.REVISION.fullmatch(expected_revision),
                "qualified warm admission requires an exact source revision")
        require(type(dependency_admission) is dependency.Admission,
                "qualified warm admission requires the complete live dependency admission")
        self.source = historical._path(source, directory=True)
        self.path = historical._path(path)
        self.expected_revision = expected_revision
        self.dependency_admission = dependency_admission
        require(dependency_admission.source == self.source
                and dependency_admission.document.get("expected_revision") == expected_revision
                and dependency_admission.document.get("fresh_dependency_build_passed") is True
                and dependency_admission.verification.get("fresh_dependency_build_passed") is True,
                "qualified warm dependency admission selects a different source or failed build")
        dependency_admission.verify_stable()
        self.proof = qualification.load_proof(self.path, expected_sha256)
        self.original_proof = qualification.base_proof(self.source)
        self.identity = _identity(self.path, maximum=qualification.MAX_PROOF_BYTES)
        require(self.identity["sha256"] == expected_sha256,
                "qualified warm proof changed after validation")
        self.diagnostic_identity = _identity(diagnostic_archive)
        self.control_identity = _identity(control_archive)
        for identity, expected, pin in (
            (self.diagnostic_identity, self.original_proof["diagnostics"]["archive"], diagnostic_sha256),
            (self.control_identity, self.original_proof["controls"]["archive"], control_sha256),
        ):
            require(type(pin) is str and pin == expected["sha256"]
                    and identity["sha256"] == pin and identity["size_bytes"] == expected["size_bytes"],
                    "qualified warm prerequisite archive differs from its selected original")
        self.measurement_sources = [_relative_identity(self.source, row["path"])
                                    for row in self.proof["measurement_sources"]]
        source_projection = qualification.verify_source_projection(self.proof, self.measurement_sources)
        dependency_projection = prerequisites.verify_dependency_projection(
            self.original_proof, dependency_admission.document)
        self.helper_sources = reader_sources()
        self.prerequisite_inputs = prerequisite_input_rows(self.proof)
        for row in (*self.helper_sources, *self.prerequisite_inputs):
            require(_relative_identity(self.source, row["path"]) == row
                    and _relative_identity(ROOT, row["path"]) == row,
                    "qualified warm helper or prerequisite input differs: " + row["path"])
        diagnostics = prerequisites.verify_prerequisites(self.original_proof,
            diagnostic_archive=Path(self.diagnostic_identity["path"]), diagnostic_sha256=diagnostic_sha256)
        controls = prerequisites.verify_control_prerequisite(self.original_proof,
            archive=Path(self.control_identity["path"]), sha256=control_sha256)
        self.summary = admission_summary(self.proof, source_projection,
            dependency_projection, diagnostics, controls)
        self.verify_stable()

    def verify_stable(self):
        require(_identity(self.path, maximum=qualification.MAX_PROOF_BYTES) == self.identity,
                "qualified warm proof changed after admission")
        for identity in (self.diagnostic_identity, self.control_identity):
            require(_identity(identity["path"]) == identity,
                    "qualified warm prerequisite archive changed after admission")
        for row in self.measurement_sources:
            require(_relative_identity(self.source, row["path"]) == row,
                    "qualified warm measurement source changed after admission: " + row["path"])
        require(reader_sources() == self.helper_sources,
                "qualified warm trusted reader changed after admission")
        for row in (*self.helper_sources, *self.prerequisite_inputs):
            require(_relative_identity(self.source, row["path"]) == row
                    and _relative_identity(ROOT, row["path"]) == row,
                    "qualified warm helper or prerequisite input changed after admission: " + row["path"])
        self.dependency_admission.verify_stable()
        return stability_summary(self.proof, self.helper_sources, self.prerequisite_inputs)
