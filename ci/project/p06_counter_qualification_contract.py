# SPDX-License-Identifier: Apache-2.0
"""Frozen source premises for explicitly selected managed counter qualification."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

import p06_dependency_admission as dependency_admission
import p06_managed_preflight_contract as preflight


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p06-managed-counter-qualification-v1"
SCOPE = "seed-free-managed-counter-qualification"
PROOF_CONTRACT_ID = "p06-counter-source-proof-v1"
SOURCE_PROOF_PATH = "ci/project/p06_counter_qualification_proof.json"
SOURCE_PROOF_SHA256 = "d12718e9b182a3c93eab346901b380031516d556dd823017a63831d4a0304b4e"
SOURCE_PROOF_DOCUMENT_SHA256 = "b91a7f84411bfd9a05058e54b50904812406c5699b76b582674d835399a6025e"
SOURCE_PROOF_BYTES = 123781
MAX_PROOF_BYTES = 256 * 1024
MAX_SOURCES = 20000
MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAX_PATH_BYTES = 4096
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
RELATIVE_PATH = re.compile(r"[A-Za-z0-9_.+()\-]+(?:/[A-Za-z0-9_.+()\-]+)*\Z")
FALSE_CLAIMS = preflight.FALSE_CLAIMS
COMPLETE_COUNTS = deepcopy(preflight.COMPLETE_COUNTS)
WARM_CONTRACT_SHA256 = preflight.WARM_CONTRACT_SHA256
PREMISE_IDS = tuple("P%02d" % number for number in range(1, 11))
SOURCE_FILES = (
    "ci/project/p06_counter_qualification_contract.py",
    SOURCE_PROOF_PATH,
    "ci/project/p06_counter_qualification_prerequisites.py",
    "ci/project/p06_counter_qualification_admission.py",
    "ci/project/p06_counter_qualification_execute.py",
    "docs/project/evidence/p06-counter-diagnostics/native/public-source-inventory-4268d2d5.json",
    "docs/designs/complete_counter_qualification_v1.md",
)
LIMITATIONS = [
    "Qualification is explicitly selected and bound before each fresh process; historical observations keep their original contracts and false claims.",
    "The frozen source proof supplies conditional premises, not execution, producer authentication, or a Boolean qualification attestation.",
    "The counter qualification result applies only to the complete fresh four-process preflight whose build, observations and dependency provenance are verified.",
    "The unchanged historical warm route, full warm coverage, performance acceptance and phase acceptance remain unavailable.",
    "System headers, compiler support files, system libraries and malicious concurrent writers remain outside complete host provenance.",
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise ValueError("qualification input is not bounded JSON data") from error


def _json_types(value, depth=0):
    require(depth <= 32, "qualification input exceeds the nesting bound")
    if type(value) is dict:
        require(len(value) <= 1000 and all(type(key) is str for key in value),
                "qualification object keys are invalid or excessive")
        for item in value.values():
            _json_types(item, depth + 1)
    elif type(value) is list:
        require(len(value) <= MAX_SOURCES, "qualification array is excessive")
        for item in value:
            _json_types(item, depth + 1)
    elif type(value) is int:
        require(0 <= value <= 2**64 - 1, "qualification integer is outside uint64")
    elif type(value) is str:
        require(len(value.encode("utf-8")) <= MAX_PROOF_BYTES, "qualification string is excessive")
    else:
        require(type(value) is bool or value is None,
                "qualification input contains a non-JSON or floating value")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate qualification JSON field")
        result[key] = value
    return result


def _integer(token):
    require(len(token) <= 20, "qualification integer token is excessive")
    value = int(token)
    require(0 <= value <= 2**64 - 1, "qualification integer token is outside uint64")
    return value


def _reject_number(_):
    raise ValueError("floating or nonfinite qualification numbers are forbidden")


def _decode(body):
    require(type(body) is bytes and 0 < len(body) <= MAX_PROOF_BYTES,
            "qualification proof must be bounded nonempty bytes")
    try:
        value = json.loads(body.decode("utf-8", errors="strict"), object_pairs_hook=_pairs,
                           parse_int=_integer, parse_float=_reject_number,
                           parse_constant=_reject_number)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ValueError("malformed qualification proof: " + str(error)) from error
    return value


def validate_proof(value):
    """Validate fixed reviewed premises without treating them as native evidence."""
    if type(value) is bytes:
        require(len(value) == SOURCE_PROOF_BYTES
                and hashlib.sha256(value).hexdigest() == SOURCE_PROOF_SHA256,
                "qualification proof differs from the trusted frozen byte identity")
        value = _decode(value)
    require(type(value) is dict, "qualification proof must be an object")
    _json_types(value)
    encoded = _canonical(value)
    require(len(encoded) <= MAX_PROOF_BYTES
            and hashlib.sha256(encoded).hexdigest() == SOURCE_PROOF_DOCUMENT_SHA256,
            "qualification proof differs from the reviewed semantic contract")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1
            and value["contract_id"] == PROOF_CONTRACT_ID,
            "qualification proof changes its version")
    require(value["measurement_contract_sha256"] == WARM_CONTRACT_SHA256,
            "qualification proof changes the frozen warm measurement")
    require(len(value["selectors"]) == 33 and len(value["components"]) == 40
            and len({row["id"] for row in value["components"]}) == 40
            and len(value["unavailable_selectors"]) == 12,
            "qualification proof changes the exact counter population")
    require(tuple(row["id"] for row in value["premises"]) == PREMISE_IDS
            and set(value["required_fresh_relationships"]) == set(PREMISE_IDS),
            "qualification proof changes its ten conditional premises")
    require(set(value["claims"]) == set(FALSE_CLAIMS)
            and all(value["claims"][name] is False for name in FALSE_CLAIMS),
            "source premises cannot assert qualification or acceptance")
    return deepcopy(value)


def load_proof(path, expected_sha256):
    require(type(expected_sha256) is str and expected_sha256 == SOURCE_PROOF_SHA256,
            "the exact independently selected frozen qualification SHA-256 is required")
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path
            and all(not parent.is_symlink() for parent in (path, *path.parents)),
            "qualification proof path must be canonical and must not traverse symlinks")
    status = path.stat()
    require(stat.S_ISREG(status.st_mode) and status.st_nlink == 1
            and status.st_size == SOURCE_PROOF_BYTES,
            "qualification proof must be a bounded unlinked regular file")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        require((before.st_dev, before.st_ino, before.st_size, before.st_nlink)
                == (status.st_dev, status.st_ino, status.st_size, 1),
                "qualification proof changed before reading")
        body = stream.read(MAX_PROOF_BYTES + 1)
        after = os.fstat(stream.fileno())
    require((before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            "qualification proof changed while reading")
    return validate_proof(body)


def _source_rows(rows):
    require(type(rows) is list and 0 < len(rows) <= MAX_SOURCES,
            "qualification source descriptors are absent or excessive")
    result = {}
    order = []
    for row in rows:
        require(type(row) is dict and set(row) == {"path", "sha256", "size_bytes"},
                "qualification source descriptor fields differ")
        path = row["path"]
        require(type(path) is str and len(path.encode("utf-8")) <= MAX_PATH_BYTES
                and RELATIVE_PATH.fullmatch(path) and str(PurePosixPath(path)) == path
                and not {".", ".."} & set(path.split("/"))
                and path not in result, "qualification source path is unsafe or duplicated")
        require(type(row["sha256"]) is str and SHA256.fullmatch(row["sha256"])
                and type(row["size_bytes"]) is int
                and 0 <= row["size_bytes"] <= MAX_SOURCE_BYTES,
                "qualification source identity is invalid")
        result[path] = row
        order.append(path)
    require(order == sorted(order), "qualification source descriptors are not sorted")
    return result


def verify_source_projection(proof, sources):
    proof = validate_proof(proof)
    actual = _source_rows(sources)
    expected = _source_rows(proof["measurement_sources"])
    for path, row in expected.items():
        require(actual.get(path) == row,
                "qualification source projection differs at " + path)
    return {
        "source_proof_sha256": SOURCE_PROOF_SHA256,
        "reviewed_source_revision": proof["reviewed_source_revision"],
        "measurement_sources_sha256": digest(proof["measurement_sources"]),
        "measurement_sources_checked": len(expected),
        "selectors": 33, "components": 40, "unavailable_selectors": 12,
        "premises": list(PREMISE_IDS),
    }


def contract():
    return {
        "schema_version": 1, "contract_id": CONTRACT_ID, "scope": SCOPE,
        "dependency_contract": dependency_admission.contract(),
        "source_proof": {"path": SOURCE_PROOF_PATH, "sha256": SOURCE_PROOF_SHA256,
                         "size_bytes": SOURCE_PROOF_BYTES},
        "measurement_contract_sha256": WARM_CONTRACT_SHA256,
        "selectors": 33, "components": 40, "unavailable_selectors": 12,
        "premises": list(PREMISE_IDS), "complete_counts": deepcopy(COMPLETE_COUNTS),
        "source_files": list(SOURCE_FILES), "false_claims": list(FALSE_CLAIMS),
        "result_field": "counter_qualification_passed",
        "result_scope": "complete-fresh-four-process-preflight",
        "limitations": list(LIMITATIONS),
    }


def contract_hash():
    return digest(contract())
