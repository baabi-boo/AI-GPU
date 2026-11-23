# SPDX-License-Identifier: Apache-2.0
"""Versioned pending-read and run-boundary observations for managed preflight."""

from copy import deepcopy
import hashlib
import json

import p06_managed_preflight_contract as preflight


CONTRACT_ID = "p06-managed-counter-lifetime-v1"
SCHEMA_VERSION = 1
SCOPE = "seed-free-managed-counter-lifetime"
PARENT_CONTRACT_ID = preflight.CONTRACT_ID
APP_FLAG = "--lifetime"
WITNESS_MARKER = "P06_MANAGED_COUNTER_LIFETIME"
WITNESS_PREFIX = WITNESS_MARKER + " "
OPERATIONS = preflight.OPERATIONS
MAX_RUNS = OPERATIONS
MAX_RECORD_BYTES = preflight.MAX_RECORD_BYTES
MAX_OUTPUT_BYTES = preflight.MAX_OUTPUT_BYTES
MAX_UINT64 = preflight.MAX_UINT64
FALSE_CLAIMS = preflight.FALSE_CLAIMS
UNRESOLVED_OBLIGATIONS = preflight.UNRESOLVED_OBLIGATIONS
PER_PROCESS = deepcopy(preflight.PER_PROCESS)
COMPLETE_COUNTS = deepcopy(preflight.COMPLETE_COUNTS)
SNAPSHOT_NAMES = preflight.SNAPSHOT_NAMES
SNAPSHOT_RESET_OFFSETS = (0, 1, OPERATIONS, OPERATIONS)

ROUTE = {
    "backend": "simx", "xlen": 64, "checked_counter_bits": 64,
    "simulation_workers": 1, "seeded": False,
}
SUCCESSFUL_RUN = {"real_call_entered": True, "completed": True, "exception": False}
IDENTITY_FIELDS = preflight.IDENTITY_FIELDS
MODEL_FIELDS = preflight.MODEL_FIELDS + ("pending_reads",)
RUN_FIELDS = (
    "ordinal", "before", "after", "real_call_entered", "completed", "exception",
    "dcr_reads_before", "dcr_reads_after", "cache_flushes_before", "cache_flushes_after",
)
PENDING_READ_FIELDS = ("sequence", "pending_before", "pending_after")
SNAPSHOT_FIELDS = ("name", "before", "after")
DESTRUCTION_FIELDS = preflight.DESTRUCTION_FIELDS
WITNESS_FIELDS = IDENTITY_FIELDS + tuple(ROUTE) + (
    "constructed_state", "runs", "snapshots", "reads", "cache_flush_reads",
    "destruction", "trace_overflow", "unresolved_obligations",
) + FALSE_CLAIMS

SOURCE_FILES = (
    ".github/workflows/p06-native-lifetime.yml",
    "ci/project/p06_native_lifetime_contract.py",
    "ci/project/p06_native_lifetime_execute.py",
    "ci/project/p06_native_lifetime_records.py",
    "docs/designs/managed_counter_lifetime_v1.md",
)
LIMITATIONS = [
    "Passing establishes only the fixed four-process managed preflight and its recorded pending-read/run-boundary observations.",
    "The lifetime record supplements the unchanged v1 transcript; absent historical observations are never reconstructed.",
    "Observed boundaries alone do not establish the source/binary-bound lifetime of all 40 selected backing components.",
    "Fresh dependency source/compile/link/loaded-product provenance and independent complete counter qualification remain unresolved.",
    "All seven qualification, warm-readiness, warm-execution and acceptance claims remain false.",
    "Transcript validation is not complete archive replay, native execution, an absolute no-wrap bound or performance acceptance.",
    "The separate native pending-read accessor probe is not one of the four managed processes or their 132 launches.",
]


def contract():
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_id": CONTRACT_ID,
        "parent_contract_id": PARENT_CONTRACT_ID,
        "scope": SCOPE,
        "app_flag": APP_FLAG,
        "witness_marker": WITNESS_MARKER,
        "route": deepcopy(ROUTE),
        "per_process": deepcopy(PER_PROCESS),
        "complete_counts": deepcopy(COMPLETE_COUNTS),
        "max_runs": MAX_RUNS,
        "max_record_bytes": MAX_RECORD_BYTES,
        "max_output_bytes": MAX_OUTPUT_BYTES,
        "snapshot_names": list(SNAPSHOT_NAMES),
        "snapshot_reset_offsets": list(SNAPSHOT_RESET_OFFSETS),
        "successful_run": deepcopy(SUCCESSFUL_RUN),
        "fields": {
            "witness": list(WITNESS_FIELDS), "model": list(MODEL_FIELDS),
            "run": list(RUN_FIELDS), "pending_read": list(PENDING_READ_FIELDS),
            "snapshot": list(SNAPSHOT_FIELDS), "destruction": list(DESTRUCTION_FIELDS),
        },
        "false_claims": list(FALSE_CLAIMS),
        "unresolved_obligations": list(UNRESOLVED_OBLIGATIONS),
        "source_files": list(SOURCE_FILES),
        "limitations": list(LIMITATIONS),
    }


def contract_hash():
    encoded = json.dumps(contract(), sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def process_identity(fmt, policy, binding_id):
    value = preflight.process_identity(fmt, policy, binding_id)
    value.update(schema_version=SCHEMA_VERSION, contract_id=CONTRACT_ID)
    return value
