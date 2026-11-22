#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Frozen same-build workspace experiment; validation executes no native work."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

import p02_wmma_fixtures as fixtures
import p06_contract as counter_reference


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = "ci/project/p06_warm_contract.json"
CONTRACT_ID = "p06-warm-workspace-v1"
FORMATS = ("fp16", "bf16")
POLICIES = ("per_operation", "reusable_single_tile")
BACKENDS = ("simx",)
OPERATIONS = 33
TIMED_OPERATIONS = 32
MAX_MANIFEST_BYTES = 256 * 1024
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_UINT64 = (1 << 64) - 1

_SOURCE_HASHES = {
    "VX_config.toml": "a1c49de52a0373b5f74706528d46bea1181c54f7769dd03994e033c7ddd710bf",
    "VX_types.toml": "f8eb0b3343f66ebe0a3c9030c8c9150c13638e7c23744b00b2fcf8ce005d5f23",
    "ci/gen_config.py": "b710a1b80c89d327adf079e61aec9f5d4f950d89342b633b6b00871e50abe165",
    "ci/project/fixtures/p02_layout_v1.json": "0543f9f4208de3ff4743fe1894d97ccf3b8cca4707e9a26acd1f3dde884725b2",
    "ci/project/fixtures/p02_tfr_v1.json": "0d8b173af178875274a7bf29886a51838be8cdb54224d55353959a639a5ea6c3",
    "ci/project/fixtures/p02_wmma_numerical_v1.json": "4102d74024e92e9887d7324b9326c0d6ad1fff206b5fad33f45c530d5bd03a73",
    "ci/project/p02_fixture_oracle.py": "12e546864a4fef5b05e10c7a04b1006bcd59376e5921ea1221c4d42668490145",
    "ci/project/p02_layout_fixture_oracle.py": "34e78c0313e2b032930615f02a790729d1c49293349728b55f7d04a29a2568a7",
    "ci/project/p02_wmma_fixtures.py": "4a672a5d3357f220120f43e5f5d7e880f7d0ba36df380d69cd1873ea4879835e",
    "ci/project/p02_wmma_numerical_fixture_oracle.py": "083450dc11712e5fc6dce7d19fb854bd9ef25b738347efd56bd07e81b079570b",
    "ci/project/p06_contract.py": "780086070739b6d3586f9b3695ad4dc31d209a7817cf1af3651160a9fe6e1376",
    "profiles/p02-tfr.json": "79a551bd7ba51b5aa4b221eeb9c8f68b0f3078e6282ce71a1f28e9bc4593a102",
    "sw/common/ai_matmul_args.h": "732bd11a5002a4486ffe89b75f082f199f4bd2436c984ddaaae63d0748f02147",
    "sw/common/ai_matmul_profile.h": "8b2eb9a819506227808537612672c08a574230736f13f840a9d83bbd35675680",
    "sw/kernel/ai/matmul.cpp": "ad3b6107f0eef91ec676412bc795ab70cd1c9f31647b2cea854de6234fe71d3e",
    "tests/regression/ai_bench_common/counters.h": "ef71a80f2624159cac03e42a60c8b3671489ee1ae89e4e9bd27941a143047acf",
    "tests/regression/sgemm_tcu/p02_fixtures.h": "1e692ad5d14e895286e57e45bf9d1730cf2380a33ccbaa486c601db838daa64e",
}

IDENTITY_KEYS = (
    "schema_version", "contract_id", "qualification_id", "sample_id",
    "format", "policy", "pair_index", "phase",
)
COUNT_KEYS = (
    "device_open_calls", "device_release_calls", "buffer_create_calls",
    "buffer_release_calls", "live_buffers", "live_requested_bytes",
    "peak_requested_payload_bytes", "premature_releases", "errors",
)
DISPATCH_KEYS = (
    "a_address", "b_address", "d_address", "a_bytes", "b_bytes", "d_bytes",
    "writes", "launches", "reads", "waits", "timed_out_waits",
    "argument_bytes", "event_results", "profiling_enabled",
)
RESULT_KEYS = ("validation", "primary", "cleanup", "complete")
MEMORY_KEYS = ("queried", "status", "free_bytes", "used_bytes")
SNAPSHOT_NAMES = ("after_open", "after_prime", "after_batch", "before_release")
MEMORY_NAMES = ("after_open", "after_create", "after_prime", "after_batch", "before_release")
OPERATION_KEYS = IDENTITY_KEYS + (
    "operation_index", "role", "case_id", "m", "n", "k", "poison",
    "begin_ns", "end_ns", "checked", "mismatches", "actual_bits", "dispatch",
    "results", "counts_before", "counts_after", "passed",
)
SUMMARY_KEYS = IDENTITY_KEYS + (
    "operations", "checked", "mismatches", "passed", "counts", "snapshots",
    "memory", "results", "host_intervals_ns", "device_release",
)


class ContractError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ContractError(message)


def _same(actual, expected, label):
    require(type(actual) is type(expected), label + ": incorrect value type")
    if type(expected) is dict:
        require(set(actual) == set(expected), label + ": missing or unknown fields")
        for key, value in expected.items():
            _same(actual[key], value, label + "." + key)
    elif type(expected) is list:
        require(len(actual) == len(expected), label + ": incorrect inventory size")
        for index, value in enumerate(expected):
            _same(actual[index], value, label + "[" + str(index) + "]")
    else:
        require(actual == expected, label + ": differs from the frozen contract")


def _read_file(path, maximum):
    path = Path(path).absolute()
    require(".." not in path.parts and not any(item.is_symlink() for item in (path, *path.parents)),
            "source input traverses a parent or symbolic link")
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_size <= maximum,
                "source input is not a bounded regular file: " + str(path))
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            body = stream.read(maximum + 1)
        require(len(body) == info.st_size and len(body) <= maximum,
                "source input changed size or exceeded its bound")
        return body
    except OSError as error:
        raise ContractError("cannot read source input: " + str(path)) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _unique(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "duplicate contract JSON field: " + key)
        value[key] = item
    return value


def _integer(token):
    require(len(token) <= 20 and not token.startswith("-"), "invalid contract integer")
    value = int(token)
    require(value <= MAX_UINT64, "contract integer exceeds uint64")
    return value


def _reject_number(_):
    raise ContractError("floating-point and nonfinite contract numbers are forbidden")


def decode_contract(body):
    require(type(body) is bytes and len(body) <= MAX_MANIFEST_BYTES, "contract must be bounded UTF-8 bytes")
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
                require(depth <= 16, "contract exceeds its nesting bound")
            elif char in "]}":
                depth -= 1
        result = json.loads(text, object_pairs_hook=_unique, parse_int=_integer,
                            parse_float=_reject_number, parse_constant=_reject_number)
    except (UnicodeError, ValueError, RecursionError, OverflowError) as error:
        raise ContractError("invalid warm contract JSON: " + str(error)) from error
    require(type(result) is dict, "contract root must be an object")
    return result


def expected_contract():
    reference_path = ROOT / "ci/project/p06_contract.py"
    require(Path(counter_reference.__file__).resolve() == reference_path,
            "counter definitions must load from the trusted repository")
    require(hashlib.sha256(_read_file(reference_path, MAX_SOURCE_BYTES)).hexdigest()
            == _SOURCE_HASHES["ci/project/p06_contract.py"], "counter definition source changed")
    reference = counter_reference.expected_contract()
    result = {
        "schema_version": 1, "contract_id": CONTRACT_ID, "contract_version": 1,
        "work_package": "P06-T01", "scope": "matched-warm-context-workspace-experiment",
        "acceptance_claimed": False, "execution_claimed": False, "phase_acceptance": False,
        "source_inputs": [{"path": path, "sha256": digest} for path, digest in sorted(_SOURCE_HASHES.items())],
        "source_matching": "one_clean_revision_and_same_binaries_per_format_both_policies",
        "profile": deepcopy(reference["profile"]), "backends": list(BACKENDS),
        "formats": list(FORMATS), "policies": list(POLICIES), "shape": [8, 4, 8],
        "fixture_suffix": "single-dense_boundaries",
        "fixture_path": "ci/project/fixtures/p02_layout_v1.json",
        "fixture_sha256": _SOURCE_HASHES["ci/project/fixtures/p02_layout_v1.json"],
        "kernel_source_sha256": _SOURCE_HASHES["sw/kernel/ai/matmul.cpp"],
        "capabilities": deepcopy(reference["capabilities"]),
        "capability_values": deepcopy(reference["capability_values"]),
        "counters": deepcopy(reference["counters"]), "geometry": deepcopy(reference["geometry"]),
        "sampling": {
            "warmup_pairs": 1, "measured_pairs": 5, "prime_operations": 1,
            "timed_operations": 32, "operations_per_process": 33,
            "pair_indices": [0, 1, 2, 3, 4, 5],
            "order": "fp16_then_bf16_pairs_ascending_alternating_reference_first_at_zero",
            "context_policy": "one_fresh_process_and_context_per_policy_batch",
            "warm_context": "prime_closed_then_32_serial_operations_each_explicitly_closed",
            "poisons": [0xDEADBEEF, 0x7FC0DEAD],
            "poison_order": "alternate_by_operation_index_prime_is_zero",
            "failed_sample_policy": "retain_and_fail_entire_attempt_no_replacements",
            "outlier_policy": "none", "optional_stopping": False,
        },
        "per_operation": {
            "launches": 1, "checked_words": 32, "useful_flops": 512,
            "input_h2d_bytes": 192, "poison_h2d_bytes": 128,
            "tensor_d2h_bytes": 128, "argument_bytes": 56,
        },
        "per_process": {
            "operations": 33, "timed_operations": 32, "launches": 33,
            "checked_words": 1056, "timed_useful_flops": 16384,
            "peak_requested_payload_bytes": 320,
            "per_operation_buffer_creates": 99, "per_operation_buffer_releases": 99,
            "resident_buffer_creates": 3, "resident_buffer_releases": 3,
        },
        "complete_matrix": {
            "processes": 24, "warmup_processes": 4, "measured_processes": 20,
            "launches": 792, "checked_words": 25344, "measured_operations": 640,
            "measured_checked_words": 20480, "measured_useful_flops": 327680,
        },
        "observation": {
            "operation_marker": "P06_WARM_OPERATION", "summary_marker": "P06_WARM_SUMMARY",
            "failure_marker": "P06_WARM_FAILURE", "success_marker": "PASSED!",
            "marker_order": "33_operations_then_summary_then_success",
            "identity_keys": list(IDENTITY_KEYS), "operation_keys": list(OPERATION_KEYS),
            "summary_keys": list(SUMMARY_KEYS), "count_keys": list(COUNT_KEYS),
            "dispatch_keys": list(DISPATCH_KEYS), "result_keys": list(RESULT_KEYS),
            "memory_keys": list(MEMORY_KEYS), "snapshot_names": list(SNAPSHOT_NAMES),
            "memory_names": list(MEMORY_NAMES),
            "operation_result_names": ["submit", "wait", "close"],
            "owner_result_names": ["create", "close"],
            "host_interval_names": ["create", "close"], "interval_keys": ["begin_ns", "end_ns"],
            "snapshot_keys": deepcopy(reference["observation"]["snapshot_keys"]),
            "release_keys": deepcopy(reference["observation"]["release_keys"]),
            "sample_id_pattern": "warm-simx-(?:fp16|bf16)-pair[0-5]-(?:per_operation|reusable_single_tile)",
            "context_id": 1, "device_index": 0, "counter_bits": 64,
            "counter_delta_policy": "after_batch_minus_after_prime_no_wrap_or_reset",
            "positive_counter_deltas": ["cycles", "instructions"],
            "disabled_counter_policy": "enabled_false_status_null_value_null",
            "profiling_enabled": False, "wait_timeout_ns": 120000000000,
            "wrapper_symbols": ["vx_buffer_create", "vx_buffer_release", "vx_device_open", "vx_device_release"],
        },
        "timing": {
            "clock": "std_chrono_steady_clock_nanoseconds",
            "primary_metric": "instrumented_host_nanoseconds_per_validated_operation",
            "begin": "immediately_before_submit",
            "end": "after_wait_exact_comparison_explicit_close_and_success_checks",
            "included": ["submit", "wait", "exact_output_comparison", "explicit_operation_close",
                         "success_checks", "minimal_fixed_storage_allocation_observer"],
            "excluded": ["input_packing", "context_create", "counter_queries", "memory_queries",
                         "trace_copy", "output_copy_for_retention", "record_serialization", "owner_close"],
            "positive_duration_required": True,
            "counter_queries_outside_primary_interval": True,
            "memory_queries_outside_primary_interval": True,
            "supervisor_duration": "separate_observation_never_corrected_or_subtracted",
            "supervisor_containment_allowance_ns": 1000,
        },
        "analysis": {
            "batch_statistic": "arithmetic_mean_of_32_primary_intervals",
            "population": "five_measured_batch_means_per_format_and_policy",
            "statistics": ["count", "minimum", "maximum", "median", "population_stddev"],
            "candidate_median_percent_of_reference_max": 95,
            "each_measured_candidate_pair_must_not_be_slower": True,
            "each_measured_candidate_pair_cycles_must_not_increase": True,
            "all_formats_must_improve": True,
            "required_validity": ["numerics", "dispatch", "ownership", "cleanup", "provenance", "resources"],
            "decision_is_phase_acceptance": False,
        },
        "budget": {"jobs_max": 2, "max_rss_bytes": 4 * 1024**3,
                   "min_free_bytes": 15 * 1024**3, "max_log_bytes": 16 * 1024**2,
                   "build_timeout_seconds": 1800, "run_timeout_seconds": 180,
                   "hosted_job_timeout_minutes": 90},
        "limitations": [
            "The contract freezes an experiment and does not claim execution, improvement or phase acceptance.",
            "Same-source policy selection isolates buffer lifetime; all policies retain queue/event creation, writes, kernel, reads and close.",
            "Host time includes minimal wrapper bookkeeping and correctness checks, not uninstrumented runtime or physical-device latency.",
            "Warm context means retained state after one prime; it does not guarantee any particular cache residency or thermal state.",
            "Batch counter deltas are modeled cumulative observations, not individual-kernel attribution or physical throughput.",
            "Requested tensor payload and simulator memory accounting are not physical memory capacity or reclamation.",
            "Five paired batches support descriptive results only; outliers, samples and rejection thresholds cannot be changed after evaluation.",
            "The accepted cold baseline and original source pins remain separate and unchanged.",
            "P06-A02/A03, native RTL and inherited gates, vendor emulation, physical FPGA and silicon remain separate obligations.",
        ],
    }
    return result


def validate_contract(contract, source=ROOT):
    _same(contract, expected_contract(), "warm contract")
    source = Path(source)
    for name, expected in _SOURCE_HASHES.items():
        require(hashlib.sha256(_read_file(source / name, MAX_SOURCE_BYTES)).hexdigest() == expected,
                "frozen warm input changed: " + name)
    for name, module in (("p02_wmma_fixtures", fixtures), ("p02_fixture_oracle", fixtures.leaf),
                         ("p02_layout_fixture_oracle", fixtures.layout),
                         ("p02_wmma_numerical_fixture_oracle", fixtures.numerical)):
        path = ROOT / "ci/project" / (name + ".py")
        require(Path(module.__file__).resolve() == path,
                "fixture helper did not load from the trusted repository: " + name)
        require(hashlib.sha256(_read_file(path, MAX_SOURCE_BYTES)).hexdigest()
                == _SOURCE_HASHES["ci/project/" + name + ".py"], "loaded fixture helper changed: " + name)
    return contract


def load_contract(source=ROOT):
    return validate_contract(decode_contract(_read_file(Path(source) / MANIFEST_PATH, MAX_MANIFEST_BYTES)), source)


def _formats(formats):
    if formats is None:
        return list(FORMATS)
    require(type(formats) is list and formats and all(type(value) is str for value in formats)
            and len(set(formats)) == len(formats) and set(formats) <= set(FORMATS),
            "format selection must be a nonempty unique supported list")
    require(formats == [fmt for fmt in FORMATS if fmt in formats], "format selection changes frozen order")
    return formats


def select_cases(contract, source=ROOT, formats=None):
    validate_contract(contract, source)
    selected = _formats(formats)
    cases = fixtures.load_cases(source)
    require(_read_file(Path(source) / "tests/regression/sgemm_tcu/p02_fixtures.h", MAX_SOURCE_BYTES)
            == fixtures.render_header(cases), "independent fixture header did not reproduce")
    inventory = {case["id"]: case for case in cases}
    result = [inventory[fmt + "-" + contract["fixture_suffix"]] for fmt in selected]
    for case in result:
        require([case[key] for key in ("m", "n", "k")] == [8, 4, 8]
                and len(case["a_words"]) == 32 and len(case["b_words"]) == 16
                and len(case["expected"]) == 32, "warm fixture geometry differs")
    return result


def process_plan(contract, formats=None):
    _same(contract, expected_contract(), "warm contract")
    result = []
    for fmt in _formats(formats):
        for pair in range(6):
            order = POLICIES if pair % 2 == 0 else tuple(reversed(POLICIES))
            for policy in order:
                identifier = f"warm-simx-{fmt}-pair{pair}-{policy}"
                result.append({"id": identifier, "backend": "simx", "format": fmt,
                               "policy": policy, "pair_index": pair,
                               "phase": "warmup" if pair == 0 else "measured"})
    return result


def poison_for(operation_index):
    require(type(operation_index) is int and 0 <= operation_index < OPERATIONS,
            "operation index must be an integer from zero through 32")
    return (0xDEADBEEF, 0x7FC0DEAD)[operation_index % 2]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        contract = load_contract(args.source_dir)
        cases = select_cases(contract, args.source_dir)
        plan = process_plan(contract)
    except (OSError, ValueError) as error:
        print("Warm contract validation failed: " + str(error), file=sys.stderr)
        return 1
    print(f"Warm contract validated: {len(cases)} fixtures, {len(plan)} processes, 792 launches; native execution not run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
