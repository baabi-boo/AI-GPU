# SPDX-License-Identifier: Apache-2.0
"""Fixed seed-free managed counter preflight; no performance admission."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

import p06_warm_contract as warm


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p06-managed-counter-preflight-v1"
SCHEMA_VERSION = 1
WARM_CONTRACT_SHA256 = "893d85401b1d5f7757d82cb7c743a89b36264fe19c7d08c239b7f216b7a8cbbd"
WITNESS_MARKER = "P06_MANAGED_COUNTER_WITNESS"
WITNESS_PREFIX = WITNESS_MARKER + " "
APP = "tests/regression/ai_counter_preflight"
FORMATS = warm.FORMATS
POLICIES = warm.POLICIES
BACKENDS = ("simx",)
OPERATIONS = 33
SNAPSHOT_NAMES = warm.SNAPSHOT_NAMES
AVAILABLE_SELECTORS = 33
UNAVAILABLE_SELECTORS = 12
HALVES_PER_SNAPSHOT = 66
MAX_OUTPUT_BYTES = 16 * 1024**2
MAX_RECORD_BYTES = 512 * 1024
MAX_JSON_DEPTH = 16
MAX_UINT64 = (1 << 64) - 1
MAX_UINT32 = (1 << 32) - 1
SHA256 = re.compile(r"[0-9a-f]{64}\Z")

FALSE_CLAIMS = (
    "qualified", "ready_for_warm", "warm_execution", "full_warm_coverage",
    "acceptance_claimed", "phase_acceptance", "performance_acceptance",
)
UNRESOLVED_OBLIGATIONS = (
    "all_40_component_lifetime_and_pending_balance",
    "dependency_source_to_loaded_binary_provenance",
    "independent_complete_counter_qualification",
)
PER_PROCESS = {
    "operations": 33, "launches": 33, "checked_words": 1056,
    "snapshots": 4, "available_queries": 132, "half_replies": 264,
    "cache_flush_reads": 33, "dcr_reads": 297,
    "unavailable_rows": 48,
}
COMPLETE_COUNTS = {
    "processes": 4, "launches": 132, "checked_words": 4224,
    "snapshots": 16, "available_queries": 528, "half_replies": 1056,
    "cache_flush_reads": 132, "dcr_reads": 1188,
    "unavailable_rows": 192,
}
BUDGET = {
    "max_rss_bytes": 4 * 1024**3, "min_free_bytes": 15 * 1024**3,
    "max_log_bytes": MAX_OUTPUT_BYTES, "jobs": 2, "threads": 1,
    "timeouts_seconds": {"configure": 120, "build": 1800, "run": 180},
    "hosted_job_minutes": 90,
}

MEASUREMENT_SOURCES = (
    APP + "/Makefile", APP + "/backend.mk", APP + "/main.cpp",
    APP + "/hooks.h", APP + "/hooks.cpp",
    "tests/regression/ai_warm_workspace/main.cpp",
    "tests/regression/ai_warm_workspace/observer.cpp",
    "tests/regression/ai_warm_workspace/observer.h",
    "tests/regression/ai_bench_common/counters.h",
    "sw/runtime/ai/contract.cpp", "sw/runtime/ai/contract.h",
    "sw/runtime/ai/runtime.cpp", "sw/runtime/ai/runtime.h",
    "sw/kernel/ai/matmul.cpp",
)
FORBIDDEN_SOURCE_ROOTS = (
    "tests/unittest/checked_counters", "tests/unittest/mpm_transport",
)
FORBIDDEN_BUILD_COMPONENTS = (
    "checked-public", "checked_counters", "access_socket", "access_cache",
    "access_memory", "access_tcu", "counter_access", "public_hooks",
)
FORBIDDEN_SYMBOLS = (
    "counter_test::", "seed_component", "clear_components",
)
PROCESS_FIELDS = (
    "id", "sample_id", "backend", "format", "policy", "pair_index", "phase",
)
IDENTITY_FIELDS = (
    "schema_version", "contract_id", "process_id", "sample_id",
    "execution_binding_sha256", "format", "policy",
)
MODEL_FIELDS = (
    "live", "idle", "any_running", "generation", "ticks", "reset_generation",
    "core_cycles", "core_instructions", "exitcode",
)
READ_FIELDS = (
    "sequence", "generation", "completed_runs", "addr", "tag", "value", "status", "completed",
    "overflow", "ticks_before", "ticks_after", "reset_before", "reset_after",
    "class_before", "class_after", "idle_before", "idle_after",
    "any_running_before", "any_running_after",
)
DESTRUCTION_FIELDS = (
    "before", "completed", "ticks_after", "reset_after", "idle_after",
)
OBSERVATION_COUNTER_FIELDS = (
    "constructed", "destroyed", "constructor_entries", "destructor_entries",
    "run_entries", "run_completed", "run_errors", "dcr_read_entries",
    "dcr_read_completed", "dcr_read_errors", "dcr_write_entries",
    "dcr_write_completed", "dcr_write_errors", "overflow_errors",
    "underflow_errors", "negative_operand_errors", "unexpected_errors",
    "violations", "generation", "read_count", "cache_flush_count",
)
OBSERVATION_FIELDS = OBSERVATION_COUNTER_FIELDS + (
    "live", "constructed_state", "destruction",
)
CP_FIELDS = (
    "control", "queue_control", "status", "error", "retired", "expected",
    "head_writeback_raw", "head_writeback_status", "runtime_tail",
    "tail_register_pair_raw", "drain_basis",
)
SNAPSHOT_FIELDS = (
    "name", "before", "after", "read_begin", "read_end", "device_refs",
    "queues", "buffers", "cache_flush_count", "cp_before", "cp_after",
)
LOADED_LIBRARY_NAMES = (
    "libramulator-vortex.so", "libramulator.so", "libsimx.so",
    "libvortex-simx.so", "libvortex.so",
)
LIBRARY_FIELDS = ("name", "path")
WITNESS_FIELDS = IDENTITY_FIELDS + (
    "backend", "xlen", "checked_counter_bits", "simulation_workers", "seeded",
    "observation", "snapshots", "reads", "cache_flush_reads", "loaded_libraries", "unresolved_obligations",
) + FALSE_CLAIMS


class ContractError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ContractError(message)


def fields(value, names, label):
    require(type(value) is dict and set(value) == set(names),
            label + ": missing or unknown fields")


def fixed(value, expected, label):
    require(type(value) is type(expected), label + ": incorrect value type")
    if type(expected) is dict:
        fields(value, expected, label)
        for key, item in expected.items():
            fixed(value[key], item, label + "." + key)
    elif type(expected) is list:
        require(len(value) == len(expected), label + ": inventory length differs")
        for index, item in enumerate(expected):
            fixed(value[index], item, label + "[" + str(index) + "]")
    else:
        require(value == expected, label + ": differs from the fixed contract")


def uint(value, label, *, bits=64, minimum=0):
    require(type(value) is int and minimum <= value < (1 << bits),
            label + ": unsigned integer is outside its bound")


def digest(value, label):
    require(type(value) is str and SHA256.fullmatch(value) is not None,
            label + ": expected lowercase SHA-256")


def absolute_path(value, label):
    require(type(value) is str and len(value.encode("utf-8")) <= 4096
            and re.fullmatch(r"/[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)*", value) is not None,
            label + ": expected a bounded normalized absolute path")
    path = PurePosixPath(value)
    require(path.is_absolute() and str(path) == value and ".." not in path.parts,
            label + ": path is not canonical")
    return value


def validate_loaded_libraries(rows, expected_paths=None):
    require(type(rows) is list and len(rows) == len(LOADED_LIBRARY_NAMES),
            "loaded libraries: inventory length differs")
    paths = []
    for name, row in zip(LOADED_LIBRARY_NAMES, rows):
        fields(row, LIBRARY_FIELDS, "loaded library " + name)
        fixed(row["name"], name, "loaded library name")
        path = absolute_path(row["path"], "loaded library " + name)
        require(PurePosixPath(path).name == name, "loaded library path/name differ")
        paths.append(path)
    require(len(set(paths)) == len(paths), "loaded library paths are repeated")
    if expected_paths is not None:
        fields(expected_paths, LOADED_LIBRARY_NAMES, "expected loaded library paths")
        for name, path in zip(LOADED_LIBRARY_NAMES, paths):
            absolute_path(expected_paths[name], "expected loaded library " + name)
            fixed(path, expected_paths[name], "loaded library " + name)
    return deepcopy(rows)


def false_claims(value, label="preflight claims"):
    require(type(value) is dict, label + ": expected an object")
    for name in FALSE_CLAIMS:
        require(name in value, label + ": missing " + name)
        fixed(value[name], False, label + "." + name)


def _unique(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "duplicate preflight JSON field: " + key)
        value[key] = item
    return value


def _integer(token):
    digits = token[1:] if token.startswith("-") else token
    require(len(digits) <= 20, "preflight integer exceeds its digit bound")
    value = int(token)
    require(-(1 << 63) <= value <= MAX_UINT64, "preflight integer exceeds its storage bound")
    return value


def _reject_number(_):
    raise ContractError("floating-point and nonfinite preflight numbers are forbidden")


def _unicode(value):
    if type(value) is str:
        value.encode("utf-8", errors="strict")
    elif type(value) is dict:
        for key, item in value.items():
            _unicode(key)
            _unicode(item)
    elif type(value) is list:
        for item in value:
            _unicode(item)


def decode_record(body):
    require(type(body) is bytes and 0 < len(body) <= MAX_RECORD_BYTES,
            "preflight record must be bounded UTF-8 bytes")
    try:
        text = body.decode("utf-8", errors="strict")
        depth = 0
        quoted = escaped = False
        for char in text:
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char in "[{":
                depth += 1
                require(depth <= MAX_JSON_DEPTH, "preflight record exceeds its nesting bound")
            elif char in "]}":
                depth -= 1
        value = json.loads(text, object_pairs_hook=_unique, parse_int=_integer,
                           parse_float=_reject_number, parse_constant=_reject_number)
        _unicode(value)
    except (UnicodeError, ValueError, RecursionError, OverflowError) as error:
        raise ContractError("invalid preflight JSON: " + str(error)) from error
    require(type(value) is dict, "preflight record root must be an object")
    return value


def _warm_contract(source):
    source = Path(source)
    require(Path(warm.__file__).resolve() == ROOT / "ci/project/p06_warm_contract.py",
            "warm contract helper did not load from the trusted repository")
    contract = warm.load_contract(source)
    body = warm._read_file(source / warm.MANIFEST_PATH, warm.MAX_MANIFEST_BYTES)
    require(hashlib.sha256(body).hexdigest() == WARM_CONTRACT_SHA256,
            "historical warm measurement manifest bytes changed")
    return contract


def _plan(warm_contract):
    result = []
    for row in warm.process_plan(warm_contract):
        if row["pair_index"] == 0:
            result.append(dict(row, id="preflight-simx-" + row["format"] + "-" + row["policy"],
                               sample_id=row["id"]))
    require(len(result) == 4, "historical warm contract does not supply four warm-up cells")
    return result


def _expected(warm_contract):
    return {
        "schema_version": SCHEMA_VERSION, "contract_id": CONTRACT_ID,
        "scope": "seed-free-managed-counter-preflight",
        **dict.fromkeys(FALSE_CLAIMS, False),
        "warm_contract": {"path": warm.MANIFEST_PATH, "contract_id": warm.CONTRACT_ID,
                          "sha256": WARM_CONTRACT_SHA256},
        "profile": deepcopy(warm_contract["profile"]),
        "formats": list(FORMATS), "policies": list(POLICIES), "backends": list(BACKENDS),
        "shape": deepcopy(warm_contract["shape"]),
        "guard": {"macro": "SIMX_CHECKED_COUNTERS", "value": "1", "bits": 64},
        "simulation_workers": 1,
        "processes": _plan(warm_contract), "per_process": dict(PER_PROCESS),
        "complete_matrix": dict(COMPLETE_COUNTS), "budget": deepcopy(BUDGET),
        "snapshot_names": list(SNAPSHOT_NAMES),
        "available_selectors": AVAILABLE_SELECTORS, "unavailable_selectors": UNAVAILABLE_SELECTORS,
        "halves_per_snapshot": HALVES_PER_SNAPSHOT,
        "witness_marker": WITNESS_MARKER,
        "record_placement": "one_witness_after_the_unchanged_warm_success_line",
        "witness_fields": list(WITNESS_FIELDS),
        "model_fields": list(MODEL_FIELDS), "read_fields": list(READ_FIELDS),
        "observation_fields": list(OBSERVATION_FIELDS),
        "destruction_fields": list(DESTRUCTION_FIELDS),
        "snapshot_fields": list(SNAPSHOT_FIELDS), "cp_fields": list(CP_FIELDS),
        "loaded_library_names": list(LOADED_LIBRARY_NAMES),
        "library_fields": list(LIBRARY_FIELDS),
        "statistical_role": "preflight_only_no_performance_sampling_or_admission",
        "failed_process_policy": "retain_and_fail_entire_attempt_no_replacements",
        "source_matching": "one_clean_revision_and_identical_binaries_per_format_both_policies",
        "required_measurement_sources": list(MEASUREMENT_SOURCES),
        "forbidden_source_roots": list(FORBIDDEN_SOURCE_ROOTS),
        "forbidden_build_components": list(FORBIDDEN_BUILD_COMPONENTS),
        "forbidden_symbols": list(FORBIDDEN_SYMBOLS),
        "unresolved_obligations": list(UNRESOLVED_OBLIGATIONS),
    }


def load_contract(source=ROOT):
    return _expected(_warm_contract(source))


def validate_contract(contract, source=ROOT):
    fixed(contract, load_contract(source), "managed preflight contract")
    return contract


def process_plan(contract=None, source=ROOT):
    if contract is None:
        contract = load_contract(source)
    else:
        validate_contract(contract, source)
    return deepcopy(contract["processes"])


def select_cases(contract, source=ROOT):
    validate_contract(contract, source)
    return warm.select_cases(_warm_contract(source), source)


def counter_inventory(contract, source=ROOT):
    validate_contract(contract, source)
    original = _warm_contract(source)
    isa = original["capability_values"]["isa_flags"]
    enabled, unavailable = [], []
    for descriptor in original["counters"]:
        required = descriptor["required_isa"]
        (enabled if required == 0 or isa & required == required else unavailable).append(deepcopy(descriptor))
    require(len(enabled) == AVAILABLE_SELECTORS and len(unavailable) == UNAVAILABLE_SELECTORS,
            "fixed counter availability differs from the managed preflight")
    return {"enabled": enabled, "unavailable": unavailable}


def process_identity(fmt, policy, binding_id):
    require(type(fmt) is str and fmt in FORMATS, "unsupported preflight format")
    require(type(policy) is str and policy in POLICIES, "unsupported preflight allocation policy")
    digest(binding_id, "preflight execution binding")
    return {
        "schema_version": SCHEMA_VERSION, "contract_id": CONTRACT_ID,
        "process_id": "preflight-simx-" + fmt + "-" + policy,
        "sample_id": "warm-simx-" + fmt + "-pair0-" + policy,
        "execution_binding_sha256": binding_id, "format": fmt, "policy": policy,
    }
