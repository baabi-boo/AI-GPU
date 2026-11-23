# SPDX-License-Identifier: Apache-2.0
"""Admit reviewed counter premises before a fresh managed lifetime execution."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
import stat
import sys

import p06_counter_qualification_contract as qualification
import p06_counter_qualification_prerequisites as prerequisites
import p06_dependency_admission as dependency
import p06_dependency_contract as dependency_contract
import p06_replay as archive_helpers


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = qualification.CONTRACT_ID
SCOPE = qualification.SCOPE
SOURCE_FILES = qualification.SOURCE_FILES
LIMITATIONS = qualification.LIMITATIONS
contract = qualification.contract
contract_hash = qualification.contract_hash
require = qualification.require
MAX_INPUT_BYTES = 64 * 1024 * 1024
ABSOLUTE_PATH = re.compile(r"/[A-Za-z0-9_./+()\-]+\Z")
REVISION = re.compile(r"[0-9a-f]{40}\Z")


def _path(value, *, directory=False):
    path = Path(value)
    require(path.is_absolute() and ABSOLUTE_PATH.fullmatch(str(path))
            and path.resolve(strict=True) == path
            and all(not parent.is_symlink() for parent in (path, *path.parents)),
            "counter qualification input must be a canonical absolute path without symlinks")
    if directory:
        require(path.is_dir(), "counter qualification source must be a directory")
    return path


def _identity(value, *, maximum=MAX_INPUT_BYTES):
    path = _path(value)
    status = path.stat()
    require(stat.S_ISREG(status.st_mode) and status.st_nlink == 1
            and 0 < status.st_size <= maximum,
            "counter qualification input must be a bounded unlinked regular file")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    digest = hashlib.sha256()
    size = 0
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        require((before.st_dev, before.st_ino, before.st_size, before.st_nlink)
                == (status.st_dev, status.st_ino, status.st_size, 1),
                "counter qualification input changed before reading")
        while body := stream.read(min(1024 * 1024, maximum + 1 - size)):
            size += len(body)
            require(size <= maximum, "counter qualification input grew past its bound")
            digest.update(body)
        after = os.fstat(stream.fileno())
    current = path.stat()
    signature = lambda value: (value.st_dev, value.st_ino, value.st_size,
                               value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)
    require(size == before.st_size and signature(before) == signature(after)
            and signature(after) == signature(current),
            "counter qualification input changed while reading")
    return {"path": str(path), "sha256": digest.hexdigest(), "size_bytes": size}


def _relative_identity(root, name):
    identity = _identity(root / name)
    return dict(identity, path=name)


def reader_sources():
    rows = {row["path"]: row for row in prerequisites.reader_sources()}
    for module in (qualification, dependency, sys.modules[__name__]):
        path = ROOT / "ci/project" / (module.__name__ + ".py")
        require(Path(module.__file__).resolve(strict=True) == path,
                "qualification admission helper is outside the trusted checkout")
        name = path.relative_to(ROOT).as_posix()
        rows[name] = _relative_identity(ROOT, name)
    name = archive_helpers.ARCHIVE_READER_PATH
    identity = _relative_identity(ROOT, name)
    require(identity["sha256"] == archive_helpers.ARCHIVE_READER_SHA256,
            "trusted qualification archive reader differs from its fixed pin")
    rows[name] = identity
    return [rows[name] for name in sorted(rows)]


def _nonacceptance(result, *, scope, consistency):
    require(type(result) is dict and result.get("schema_version") == 1
            and type(result["schema_version"]) is int
            and result.get("contract_id") == prerequisites.CONTRACT_ID
            and result.get("scope") == scope and result.get("outcome") == "pass"
            and result.get(consistency) is True
            and result.get("native_execution") == "not_run"
            and result.get("retained_code_executed") is False
            and all(result.get(name) is False for name in qualification.FALSE_CLAIMS),
            "qualification prerequisite is not a verified non-acceptance result")


def admission_summary(proof, source_projection, dependency_projection, diagnostics, controls):
    """Compose internally verified evidence; this function does not verify originals."""
    proof = qualification.validate_proof(proof)
    require(source_projection == qualification.verify_source_projection(proof, proof["measurement_sources"]),
            "qualification source projection summary differs")
    require(dependency_projection == {
        "source_files": len(proof["dependency_sources"]),
        "revision": proof["dependency_revision"],
        "tree": dependency_contract.PINS["ramulator"]["tree"],
        "projection_sha256": qualification.digest(proof["dependency_sources"])},
        "qualification dependency projection summary differs")
    _nonacceptance(diagnostics, scope="pinned-diagnostic-prerequisites-only",
                   consistency="diagnostic_prerequisites_consistent")
    _nonacceptance(controls, scope="pinned-separate-control-prerequisites-only",
                   consistency="control_prerequisites_consistent")
    for value, expected in ((diagnostics, proof["diagnostics"]), (controls, proof["controls"])):
        require(value.get("archive") == expected["archive"]
                and value.get("source_revision") == expected["source_revision"],
                "qualification prerequisite original identity differs")
    require(diagnostics.get("public_source_inventory_sha256")
            == proof["diagnostics"]["public_source_inventory"]["sha256"]
            and controls.get("projected_measurement_sources") == len(proof["measurement_sources"])
            and controls.get("measurement_projection_sha256") == qualification.digest(proof["measurement_sources"])
            and controls.get("managed_population_included") is False,
            "qualification prerequisite projection differs")
    return {"schema_version": 1, "contract_id": CONTRACT_ID,
        "scope": "prelaunch-counter-source-prerequisites",
        "source_proof_sha256": qualification.SOURCE_PROOF_SHA256,
        "qualification_contract_sha256": contract_hash(),
        "source_projection": deepcopy(source_projection),
        "dependency_projection": deepcopy(dependency_projection),
        "diagnostics": deepcopy(diagnostics), "controls": deepcopy(controls),
        "native_execution": "not_run", "counter_qualification_passed": False,
        **dict.fromkeys(qualification.FALSE_CLAIMS, False)}


def stability_summary(proof, helper_sources, prerequisite_inputs):
    proof = qualification.validate_proof(proof)
    qualification._source_rows(helper_sources)
    qualification._source_rows(prerequisite_inputs)
    require(prerequisite_inputs == [proof["diagnostics"]["public_source_inventory"]],
            "qualification prerequisite input inventory differs")
    return {"proof_sha256": qualification.SOURCE_PROOF_SHA256,
        "measurement_sources_sha256": qualification.digest(proof["measurement_sources"]),
        "helper_sources_sha256": qualification.digest(helper_sources),
        "prerequisite_inputs_sha256": qualification.digest(prerequisite_inputs),
        "diagnostic_archive_sha256": proof["diagnostics"]["archive"]["sha256"],
        "control_archive_sha256": proof["controls"]["archive"]["sha256"]}


class Admission:
    def __init__(self, path, expected_sha256, *, source, expected_revision,
                 dependency_admission, diagnostic_archive, diagnostic_sha256,
                 control_archive, control_sha256):
        require(type(expected_revision) is str and REVISION.fullmatch(expected_revision),
                "counter qualification requires an exact source revision")
        require(type(dependency_admission) is dependency.Admission,
                "counter qualification requires the complete live dependency admission")
        self.source = _path(source, directory=True)
        self.path = _path(path)
        self.expected_revision = expected_revision
        self.dependency_admission = dependency_admission
        require(dependency_admission.source == self.source
                and dependency_admission.document.get("expected_revision") == expected_revision
                and dependency_admission.document.get("fresh_dependency_build_passed") is True
                and dependency_admission.verification.get("fresh_dependency_build_passed") is True,
                "counter qualification dependency admission selects a different source or failed build")
        dependency_admission.verify_stable()
        self.proof = qualification.load_proof(self.path, expected_sha256)
        self.identity = _identity(self.path, maximum=qualification.MAX_PROOF_BYTES)
        require(self.identity["sha256"] == expected_sha256,
                "counter qualification proof changed after validation")
        self.diagnostic_identity = _identity(diagnostic_archive)
        self.control_identity = _identity(control_archive)
        for identity, expected, pin in (
            (self.diagnostic_identity, self.proof["diagnostics"]["archive"], diagnostic_sha256),
            (self.control_identity, self.proof["controls"]["archive"], control_sha256),
        ):
            require(type(pin) is str and pin == expected["sha256"]
                    and identity["sha256"] == pin and identity["size_bytes"] == expected["size_bytes"],
                    "counter qualification prerequisite archive differs from its selected original")
        self.measurement_sources = [_relative_identity(self.source, row["path"])
                                    for row in self.proof["measurement_sources"]]
        source_projection = qualification.verify_source_projection(self.proof, self.measurement_sources)
        dependency_projection = prerequisites.verify_dependency_projection(
            self.proof, dependency_admission.document)
        self.helper_sources = reader_sources()
        self.prerequisite_inputs = [_relative_identity(ROOT, self.proof["diagnostics"]["public_source_inventory"]["path"])]
        require(self.prerequisite_inputs == [self.proof["diagnostics"]["public_source_inventory"]],
                "qualification public source inventory differs from its reviewed bytes")
        for row in (*self.helper_sources, *self.prerequisite_inputs):
            require(_relative_identity(self.source, row["path"]) == row,
                    "qualification executing reader differs from selected source: " + row["path"])
        diagnostics = prerequisites.verify_prerequisites(self.proof,
            diagnostic_archive=Path(self.diagnostic_identity["path"]), diagnostic_sha256=diagnostic_sha256)
        controls = prerequisites.verify_control_prerequisite(self.proof,
            archive=Path(self.control_identity["path"]), sha256=control_sha256)
        self.summary = admission_summary(self.proof, source_projection,
            dependency_projection, diagnostics, controls)
        self.verify_stable()

    def verify_stable(self):
        require(_identity(self.path, maximum=qualification.MAX_PROOF_BYTES) == self.identity,
                "qualification proof changed after admission")
        for identity in (self.diagnostic_identity, self.control_identity):
            require(_identity(identity["path"]) == identity,
                    "qualification prerequisite archive changed after admission")
        for row in self.measurement_sources:
            require(_relative_identity(self.source, row["path"]) == row,
                    "qualification measurement source changed after admission: " + row["path"])
        require(reader_sources() == self.helper_sources,
                "qualification trusted reader changed after admission")
        for row in (*self.helper_sources, *self.prerequisite_inputs):
            require(_relative_identity(self.source, row["path"]) == row
                    and _relative_identity(ROOT, row["path"]) == row,
                    "qualification helper or prerequisite input changed after admission: " + row["path"])
        self.dependency_admission.verify_stable()
        return stability_summary(self.proof, self.helper_sources, self.prerequisite_inputs)
