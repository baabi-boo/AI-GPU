# SPDX-License-Identifier: Apache-2.0
"""Frozen source extension and population for explicit qualified warm execution."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import os
from pathlib import Path
import stat

import p06_counter_qualification_contract as historical
import p06_warm_contract as warm


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p06-qualified-warm-workspace-v1"
SCOPE = "qualified-matched-warm-context-workspace-experiment"
PROOF_CONTRACT_ID = "p06-qualified-warm-source-extension-v1"
SOURCE_PROOF_PATH = "ci/project/p06_qualified_warm_proof.json"
SOURCE_PROOF_SHA256 = "172721c671ddaa79541dde9c37c154b5ab5a99b8abb0caabf2e07036dd429efb"
SOURCE_PROOF_DOCUMENT_SHA256 = "cd3a355495ee79d147b579cbd84cb58c8b6e0eb0743eb98f080b0ccc10d57a0e"
SOURCE_PROOF_BYTES = 21505
MAX_PROOF_BYTES = historical.MAX_PROOF_BYTES
CHANGED_SOURCE = "tests/regression/ai_counter_preflight/main.cpp"
FALSE_CLAIMS = historical.FALSE_CLAIMS
PREMISE_IDS = historical.PREMISE_IDS
WARM_CONTRACT_SHA256 = historical.WARM_CONTRACT_SHA256
COMPLETE_COUNTS = {name: count * 6 for name, count in historical.COMPLETE_COUNTS.items()}
SOURCE_FILES = tuple(sorted(set(historical.SOURCE_FILES) | {
    "ci/project/p06_qualified_warm_contract.py", SOURCE_PROOF_PATH,
    "ci/project/p06_qualified_warm_admission.py", "ci/project/p06_qualified_warm_execute.py",
    "ci/project/p06_qualified_warm_records.py", "docs/designs/qualified_warm_workspace_v1.md",
}))
LIMITATIONS = [
    "This explicit warm route applies the unchanged counter premises through a separately pinned native caller extension; historical proof and prerequisite populations remain unchanged.",
    "All 24 fresh processes require their own complete numerical, source/build/load, checked-counter and lifetime evidence; the preceding four-process result does not qualify them.",
    "The frozen host-time and modeled-cycle predicates are experimental results, not performance or phase acceptance, physical-device latency, power or energy.",
    "Every prime and warm-up pair is retained but excluded from measured criteria; no sample replacement, outlier removal or optional stopping is permitted.",
    "The source extension is a conditional premise requiring independent review, not execution evidence or producer authentication.",
    "System headers, compiler support files, system libraries and malicious concurrent writers remain outside complete host provenance.",
]
require = historical.require
digest = historical.digest


def base_proof(source=ROOT):
    return historical.load_proof(Path(source) / historical.SOURCE_PROOF_PATH,
                                 historical.SOURCE_PROOF_SHA256)


def process_plan(source=ROOT):
    return [dict(row, sample_id=row["id"])
            for row in warm.process_plan(warm.load_contract(source))]


def sampling_binding(source=ROOT):
    return {"contract_sha256": WARM_CONTRACT_SHA256,
            "sampling": deepcopy(warm.load_contract(source)["sampling"]),
            "processes": process_plan(source)}


def validate_proof(value):
    if type(value) is bytes:
        require(len(value) == SOURCE_PROOF_BYTES
                and hashlib.sha256(value).hexdigest() == SOURCE_PROOF_SHA256,
                "qualified warm proof differs from its frozen byte identity")
        value = historical._decode(value)
    require(type(value) is dict, "qualified warm proof must be an object")
    historical._json_types(value)
    require(digest(value) == SOURCE_PROOF_DOCUMENT_SHA256,
            "qualified warm proof differs from its reviewed semantic contract")
    original = base_proof()
    require(type(value["schema_version"]) is int and value["schema_version"] == 1
            and value["contract_id"] == PROOF_CONTRACT_ID,
            "qualified warm proof version differs")
    require(value["base_source_proof"] == {
        "path": historical.SOURCE_PROOF_PATH, "sha256": historical.SOURCE_PROOF_SHA256,
        "size_bytes": historical.SOURCE_PROOF_BYTES}, "qualified warm base proof differs")
    before = historical._source_rows(original["measurement_sources"])
    after = historical._source_rows(value["measurement_sources"])
    changes = value["source_changes"]
    require(len(changes) == 1 and changes[0]["before"] == before[CHANGED_SOURCE]
            and changes[0]["after"] == after[CHANGED_SOURCE]
            and set(before) == set(after), "qualified warm source extension differs")
    require([name for name in before if before[name] != after[name]] == [CHANGED_SOURCE],
            "qualified warm extension changes an unreviewed measurement source")
    require(value["measurement_contract_sha256"] == WARM_CONTRACT_SHA256
            and value["sampling"] == warm.load_contract(ROOT)["sampling"]
            and value["processes"] == process_plan(ROOT)
            and value["complete_counts"] == COMPLETE_COUNTS,
            "qualified warm sampling contract differs")
    require(tuple(value["premises"]) == PREMISE_IDS
            and value["claims"] == dict.fromkeys(FALSE_CLAIMS, False),
            "qualified warm proof changes premises or asserts acceptance")
    return deepcopy(value)


def load_proof(path, expected_sha256):
    require(type(expected_sha256) is str and expected_sha256 == SOURCE_PROOF_SHA256,
            "the exact independently selected qualified warm proof SHA-256 is required")
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path
            and all(not parent.is_symlink() for parent in (path, *path.parents)),
            "qualified warm proof path must be canonical without symlinks")
    status = path.stat()
    require(stat.S_ISREG(status.st_mode) and status.st_nlink == 1
            and status.st_size == SOURCE_PROOF_BYTES,
            "qualified warm proof must be a bounded unlinked regular file")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        signature = lambda row: (row.st_dev, row.st_ino, row.st_size,
                                 row.st_mtime_ns, row.st_ctime_ns, row.st_nlink)
        require(signature(before) == signature(status), "qualified warm proof changed before reading")
        body = stream.read(MAX_PROOF_BYTES + 1)
        after = os.fstat(stream.fileno())
    require(signature(before) == signature(after) == signature(path.stat()),
            "qualified warm proof changed while reading")
    return validate_proof(body)


def verify_source_projection(proof, sources):
    proof = validate_proof(proof)
    actual = historical._source_rows(sources)
    expected = historical._source_rows(proof["measurement_sources"])
    for path, row in expected.items():
        require(actual.get(path) == row, "qualified warm source projection differs at " + path)
    return {"source_proof_sha256": SOURCE_PROOF_SHA256,
        "historical_source_proof_sha256": historical.SOURCE_PROOF_SHA256,
        "measurement_sources_sha256": digest(proof["measurement_sources"]),
        "measurement_sources_checked": len(expected), "changed_sources": [CHANGED_SOURCE],
        "selectors": 33, "components": 40, "unavailable_selectors": 12,
        "premises": list(PREMISE_IDS)}


def contract():
    return {"schema_version": 1, "contract_id": CONTRACT_ID, "scope": SCOPE,
        "historical_counter_contract": historical.contract(),
        "source_extension": {"path": SOURCE_PROOF_PATH, "sha256": SOURCE_PROOF_SHA256,
                             "size_bytes": SOURCE_PROOF_BYTES},
        "warm_sampling": sampling_binding(), "complete_counts": deepcopy(COMPLETE_COUNTS),
        "native_arguments": ["--lifetime", "--qualified-warm"],
        "source_files": list(SOURCE_FILES), "false_claims": list(FALSE_CLAIMS),
        "result_field": "qualified_warm_passed",
        "result_scope": "recorded-complete-24-process-warm-attempt-only",
        "limitations": list(LIMITATIONS)}


def contract_hash():
    return digest(contract())
