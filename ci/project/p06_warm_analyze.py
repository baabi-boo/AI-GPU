#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate warm records and report conditional statistics with qualification blocked."""

from __future__ import annotations

import argparse
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import sys

from p03_execution_records import qualification_id
import p06_warm_contract as manifest
from p06_warm_records import verify_output


ROOT = manifest.ROOT
REVISION = re.compile(r"[0-9a-f]{40}\Z")
MAX_INPUT_BYTES = 64 * 1024 * 1024
PROCESS_FIELDS = {
    "id", "backend", "format", "policy", "pair_index", "phase", "sample_id",
    "command_id", "outcome", "qualification_id", "build_qualification_id",
    "binding", "log", "process_duration_seconds", "observation",
}
BUILD_FIELDS = {
    "contract_id", "contract_sha256", "source", "backend", "format", "case", "corpus",
    "profile_sha256", "kernel_source_sha256", "compiler_records", "effective_headers",
    "generated_identity", "generated_header_macros", "expected_expanded_header_macros",
    "expected_backend_header_macros", "artifacts", "tools", "dependencies", "sampling",
    "performance_environment",
}
LIMITATIONS = [
    "This analyzes retained observations and performs no native execution.",
    "The caller must independently verify archive, command, compiler, source, resource and producer provenance before interpreting the conditional statistics.",
    "Raw logs, exact observations and same-build bindings are revalidated here; a supplied document is not proof of archive provenance.",
    "The primary metric is instrumented host time including correctness checks and fixed observer work, not physical-device or uninstrumented runtime latency.",
    "All primes and the complete warm-up pairs are excluded from the conditional criteria but retained in diagnostics.",
    "The descriptive population is five measured batch means per format and policy; process separation does not establish statistical independence.",
    "No sample replacement, outlier removal, optional stopping, observer-overhead subtraction or supervisor-delay correction is applied.",
    "Reported RV64 host MPM counters lose their high 32 bits; positive monotonic values and a small workload do not establish an absolute no-wrap bound.",
    "Reported counter differences and their comparisons are conditional diagnostics, not qualified modeled-cycle evidence, individual-kernel latency, physical speed, power or energy.",
    "Full hypothesis qualification is blocked regardless of the host-time or reported-counter predicates; performance, P06-A02/A03, RTL, vendor, synthesis and physical obligations remain separate.",
]


class AnalysisError(ValueError):
    """The supplied observations cannot support the fixed complete experiment."""


def require(condition, message):
    if not condition:
        raise AnalysisError(message)


def _same(actual, expected, label):
    try:
        manifest._same(actual, expected, label)
    except ValueError as error:
        raise AnalysisError(str(error)) from error


def _keys(value, expected, label):
    require(type(value) is dict and set(value) == set(expected), label + ": incorrect fields")


def _full_hypothesis_qualification():
    """Keep missing transport evidence independent of favorable reported values."""
    return {
        "status": "blocked", "qualified": False,
        "finding_id": "P06-WARM-RV64-MPM-HIGH-HALF",
        "route": "rv64_p02_tfr_simx_host_mpm",
        "counter_transport": "unqualified_low_32_bits",
        "absolute_no_wrap_bound": "not_established",
        "reason": "The RV64 host MPM path drops the high half. Positive monotonic reported values can reverse the true paired cycle comparison; no independent absolute no-wrap bound is established.",
        "required_evidence": [
            "Independently reviewed coupled SimX/RTL host-counter transport repair with source-bound native boundary, parity and required timing/synthesis qualification, or a separately reviewed rigorous absolute no-wrap bound for every available cumulative counter.",
            "A reviewed qualification implementation and a fresh complete source-bound matched attempt; retained low words cannot be upgraded by a caller assertion or a changed source-revision label.",
        ],
    }


def _ratio(numerator, denominator):
    require(type(numerator) is int and numerator >= 0
            and type(denominator) is int and denominator > 0, "invalid rational operands")
    exact = Fraction(numerator, denominator)
    return {"numerator": exact.numerator, "denominator": exact.denominator,
            "value": float(exact)}


def _statistics(totals):
    require(len(totals) == 5 and all(type(value) is int and value > 0 for value in totals),
            "statistics require exactly five positive integer batch totals")
    ordered = sorted(totals)
    values = [Fraction(value, manifest.TIMED_OPERATIONS) for value in totals]
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return {"count": 5, "unit": "nanoseconds_per_validated_operation",
            "minimum": _ratio(ordered[0], manifest.TIMED_OPERATIONS),
            "maximum": _ratio(ordered[-1], manifest.TIMED_OPERATIONS),
            "median": _ratio(ordered[2], manifest.TIMED_OPERATIONS),
            "population_variance_ns2": _ratio(variance.numerator, variance.denominator),
            "population_stddev": math.sqrt(float(variance))}


def _builds(build_bindings, contract, expected_revision):
    require(type(expected_revision) is str and REVISION.fullmatch(expected_revision) is not None,
            "expected source revision must be a lowercase Git SHA-1")
    _keys(build_bindings, ("simx-fp16", "simx-bf16"), "warm build bindings")
    contract_digest = hashlib.sha256(manifest._read_file(
        ROOT / manifest.MANIFEST_PATH, manifest.MAX_MANIFEST_BYTES)).hexdigest()
    common_source = None
    identities = {}
    cases = {case["format"]: case for case in manifest.select_cases(contract)}
    for fmt in manifest.FORMATS:
        binding = build_bindings["simx-" + fmt]
        _keys(binding, BUILD_FIELDS, "warm build binding")
        for key, expected in (("contract_id", manifest.CONTRACT_ID),
                              ("contract_sha256", contract_digest), ("backend", "simx"),
                              ("format", fmt), ("case", cases[fmt]),
                              ("sampling", contract["sampling"]),
                              ("performance_environment", {"PERF": "1"})):
            require(key in binding, "build binding lacks " + key)
            _same(binding[key], expected, "build binding." + key)
        source = binding.get("source")
        require(type(source) is dict and type(source.get("checkout")) is dict,
                "build binding lacks the source snapshot")
        checkout = source["checkout"]
        for key, expected in (("revision", expected_revision), ("dirty", False),
                              ("changed_paths", []), ("untracked_paths", []),
                              ("blockers", []), ("outcome", "pass")):
            require(key in checkout, "source checkout lacks " + key)
            _same(checkout[key], expected, "source checkout." + key)
        require(type(checkout.get("tree")) is str and REVISION.fullmatch(checkout["tree"]) is not None,
                "source checkout lacks a valid Git tree")
        if common_source is None:
            common_source = source
        else:
            _same(source, common_source, "cross-format source snapshot")
        identities[fmt] = qualification_id(binding)
    return identities, cases, common_source, contract_digest


def _observations(processes, raw_logs, build_bindings, contract, build_ids, cases, contract_digest):
    plan = manifest.process_plan(contract)
    require(type(processes) is list and len(processes) == len(plan),
            "analysis requires the complete 24-process inventory")
    _keys(raw_logs, (row["id"] for row in plan), "warm raw log inventory")
    batches = []
    seen_digests = set()
    for process, planned in zip(processes, plan):
        _keys(process, PROCESS_FIELDS, "warm process")
        for key, expected in planned.items():
            _same(process[key], expected, "warm process." + key)
        for key, expected in (("sample_id", planned["id"]), ("command_id", planned["id"]),
                              ("outcome", "pass"), ("log", "logs/" + planned["id"] + ".log"),
                              ("build_qualification_id", build_ids[planned["format"]])):
            _same(process[key], expected, "warm process." + key)
        binding = {"contract_id": manifest.CONTRACT_ID, "contract_sha256": contract_digest,
                   "build_qualification_id": build_ids[planned["format"]],
                   "build": build_bindings["simx-" + planned["format"]], "process": planned}
        binding_id = qualification_id(binding)
        _same(process["qualification_id"], binding_id, "warm process qualification")
        observation = verify_output(raw_logs[planned["id"]], case=cases[planned["format"]],
            fmt=planned["format"], policy=planned["policy"], binding_id=binding_id,
            sample_id=planned["id"], pair_index=planned["pair_index"], phase=planned["phase"],
            contract=contract)
        _same(process["observation"], observation, "revalidated raw observation")
        require(observation["raw_log_sha256"] not in seen_digests, "a raw log was reused")
        seen_digests.add(observation["raw_log_sha256"])
        duration = process["process_duration_seconds"]
        require(type(duration) in (int, float) and math.isfinite(duration) and duration >= 0,
                "process duration must be finite and nonnegative")
        intervals = observation["summary"]["host_intervals_ns"]
        span = intervals["close"]["end_ns"] - intervals["create"]["begin_ns"]
        require(span <= math.ceil(duration * 1_000_000_000)
                + contract["timing"]["supervisor_containment_allowance_ns"],
                "owner lifetime exceeds supervised process duration")
        durations = observation["timed_operation_durations_ns"]
        require(len(durations) == manifest.TIMED_OPERATIONS
                and all(type(value) is int and value > 0 for value in durations),
                "warm batch requires 32 positive integer operation durations")
        cycles = next(row for row in observation["counter_deltas"] if row["name"] == "cycles")
        require(cycles["available"] is True and type(cycles["value"]) is int and cycles["value"] > 0,
                "warm batch cycles must be available and positive")
        batches.append({**planned, "build_qualification_id": build_ids[planned["format"]],
            "qualification_id": binding_id, "raw_log_sha256": observation["raw_log_sha256"],
            "included_in_conditional_criteria": planned["phase"] == "measured", "timed_operations": 32,
            "prime_duration_ns": observation["operation_durations_ns"][0],
            "operation_durations_ns": deepcopy(observation["operation_durations_ns"]),
            "timed_total_ns": sum(durations), "batch_mean_ns": _ratio(sum(durations), 32),
            "reported_active_cycles": cycles["value"],
            "reported_active_cycles_per_useful_flop": _ratio(cycles["value"], 16384),
            "reported_counter_deltas": deepcopy(observation["counter_deltas"]),
            "process_duration_seconds": duration})
    return batches


def _format_result(fmt, batches, contract, build_id):
    reference, candidate = manifest.POLICIES
    selected = [row for row in batches if row["format"] == fmt and row["included_in_conditional_criteria"]]
    by_pair = {(row["pair_index"], row["policy"]): row for row in selected}
    totals = {policy: [by_pair[index, policy]["timed_total_ns"] for index in range(1, 6)]
              for policy in manifest.POLICIES}
    medians = {policy: sorted(values)[2] for policy, values in totals.items()}
    pairs = []
    for index in range(1, 6):
        old, new = (by_pair[index, policy] for policy in manifest.POLICIES)
        pairs.append({"pair_index": index, "reference_sample_id": old["id"],
            "candidate_sample_id": new["id"],
            "reference_mean_ns": deepcopy(old["batch_mean_ns"]),
            "candidate_mean_ns": deepcopy(new["batch_mean_ns"]),
            "candidate_reference_host_ratio": _ratio(new["timed_total_ns"], old["timed_total_ns"]),
            "reference_reported_active_cycles": old["reported_active_cycles"],
            "candidate_reported_active_cycles": new["reported_active_cycles"],
            "candidate_reference_reported_cycle_ratio": _ratio(new["reported_active_cycles"], old["reported_active_cycles"]),
            "candidate_host_time_not_slower": new["timed_total_ns"] <= old["timed_total_ns"],
            "candidate_reported_cycles_not_increased": new["reported_active_cycles"] <= old["reported_active_cycles"]})
    criteria = {
        "host_median_at_most_95_percent_of_reference": medians[candidate] * 100
            <= medians[reference] * contract["analysis"]["candidate_median_percent_of_reference_max"],
        "no_slower_measured_host_pair": all(row["candidate_host_time_not_slower"] for row in pairs),
        "no_increased_measured_pair_reported_cycles": all(row["candidate_reported_cycles_not_increased"] for row in pairs),
    }
    return {"format": fmt, "build_qualification_id": build_id,
            "policy_statistics": {policy: _statistics(values) for policy, values in totals.items()},
            "pairs": pairs, "candidate_reference_median_ratio": _ratio(medians[candidate], medians[reference]),
            "conditional_criteria": criteria,
            "failed_conditional_criteria": [name for name, passed in criteria.items() if not passed],
            "conditional_criteria_satisfied": all(criteria.values())}


def analyze_processes(processes, raw_logs, *, build_bindings, contract, expected_revision):
    """Revalidate raw observations; the caller verifies complete packet provenance."""
    try:
        manifest.validate_contract(contract)
        build_ids, cases, source, contract_digest = _builds(build_bindings, contract, expected_revision)
        batches = _observations(processes, raw_logs, build_bindings, contract, build_ids, cases, contract_digest)
        formats = [_format_result(fmt, batches, contract, build_ids[fmt]) for fmt in manifest.FORMATS]
        conditional_satisfied = all(row["conditional_criteria_satisfied"] for row in formats)
        return {"schema_version": 2, "contract_id": manifest.CONTRACT_ID,
            "analysis_scope": "warm_workspace_raw_record_validation_and_fixed_batch_statistics",
            "raw_record_validation": "pass", "archive_provenance_validation": "required_from_caller",
            "native_execution": "not_run", "performance_acceptance": False, "phase_acceptance": False,
            "acceptance_claimed": False, "hypothesis_evaluation": "blocked",
            "full_hypothesis_qualification": _full_hypothesis_qualification(),
            "conditional_evaluation": "satisfied" if conditional_satisfied else "not_satisfied",
            "conditional_evaluation_scope": "instrumented_host_time_and_unqualified_reported_counter_predicates",
            "source_revision": expected_revision, "source_tree": source["checkout"]["tree"],
            "source_snapshot_sha256": qualification_id(source), "contract_sha256": contract_digest,
            "counts": deepcopy(contract["complete_matrix"]),
            "excluded_warmup_processes": [row["id"] for row in batches if not row["included_in_conditional_criteria"]],
            "excluded_prime_operations": 24, "batches": batches, "formats": formats,
            "conditional_criteria_arithmetic": "exact_integer_cross_products_of_batch_totals",
            "limitations": list(LIMITATIONS)}
    except AnalysisError:
        raise
    except (ValueError, TypeError, KeyError, IndexError, StopIteration, OverflowError) as error:
        raise AnalysisError("invalid warm analysis input: " + str(error)) from error


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate analysis JSON field")
        result[key] = value
    return result


def _nonfinite(_):
    raise AnalysisError("nonfinite analysis JSON number")


def _finite_float(token):
    value = float(token)
    require(math.isfinite(value), "nonfinite analysis JSON number")
    return value


def _read_input(path):
    body = manifest._read_file(path, MAX_INPUT_BYTES)
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
                require(depth <= 32, "analysis JSON exceeds its nesting bound")
            elif char in "]}":
                depth -= 1
        value = json.loads(text, object_pairs_hook=_unique, parse_float=_finite_float,
                           parse_constant=_nonfinite)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise AnalysisError("invalid analysis JSON: " + str(error)) from error
    _keys(value, ("schema_version", "build_bindings", "processes", "raw_logs"), "analysis input")
    _same(value["schema_version"], 1, "analysis input version")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path,
                        help="bounded JSON with schema_version, build_bindings, processes and raw_logs")
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", type=Path, help="new JSON output; never overwrites an existing file")
    args = parser.parse_args()
    try:
        supplied = _read_input(args.input)
        result = analyze_processes(supplied["processes"], supplied["raw_logs"],
            build_bindings=supplied["build_bindings"], contract=manifest.load_contract(),
            expected_revision=args.source_revision)
        text = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output is None:
            sys.stdout.write(text)
        else:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(text)
            print(json.dumps({"schema_version": result["schema_version"],
                "raw_record_validation": result["raw_record_validation"],
                "archive_provenance_validation": result["archive_provenance_validation"],
                "native_execution": "not_run", "hypothesis_evaluation": result["hypothesis_evaluation"],
                "full_hypothesis_qualification": result["full_hypothesis_qualification"],
                "conditional_evaluation": result["conditional_evaluation"],
                "acceptance_claimed": False, "report": str(args.output)}, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, OverflowError) as error:
        print("warm analysis rejected: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
