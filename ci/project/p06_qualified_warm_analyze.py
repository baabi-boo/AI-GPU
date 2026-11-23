# SPDX-License-Identifier: Apache-2.0
"""Frozen arithmetic for the population already reconstructed by complete replay."""

from copy import deepcopy

import p06_qualified_warm_contract as qualification
import p06_warm_analyze as arithmetic
import p06_warm_contract as warm
from p03_execution_records import qualification_id


CONTRACT_ID = "p06-qualified-warm-analysis-v1"
require = qualification.require


def analyze_population(processes, build_bindings, *, expected_revision):
    """Internal arithmetic only; this function does not admit or authenticate packets."""
    require(type(expected_revision) is str and arithmetic.REVISION.fullmatch(expected_revision),
            "qualified warm analysis requires an exact source revision")
    contract = warm.load_contract(qualification.ROOT)
    plan = qualification.process_plan()
    require(type(processes) is list and len(processes) == len(plan),
            "qualified warm analysis requires all 24 processes")
    require(type(build_bindings) is dict
            and set(build_bindings) == {"simx-fp16", "simx-bf16"},
            "qualified warm analysis requires both common format builds")
    build_ids = {fmt: qualification_id(build_bindings["simx-" + fmt]) for fmt in warm.FORMATS}
    batches = []
    seen = set()
    for planned, process in zip(plan, processes):
        require(type(process) is dict and process.get("outcome") == "pass",
                "qualified warm analysis received an incomplete process")
        for key, expected in planned.items():
            arithmetic._same(process.get(key), expected, "qualified warm analysis process." + key)
        require(process.get("build_binding_sha256") == build_ids[planned["format"]],
                "qualified warm analysis common build differs")
        binding_id = process["execution_binding_sha256"]
        require(type(binding_id) is str and qualification.historical.SHA256.fullmatch(binding_id),
                "qualified warm analysis execution identity differs")
        observation = process["observation"]["warm"]
        durations = observation["timed_operation_durations_ns"]
        all_durations = observation["operation_durations_ns"]
        require(type(durations) is list and len(durations) == warm.TIMED_OPERATIONS
                and all(type(value) is int and value > 0 for value in durations)
                and type(all_durations) is list and len(all_durations) == warm.OPERATIONS
                and type(all_durations[0]) is int and all_durations[0] > 0
                and all_durations[1:] == durations,
                "qualified warm analysis requires one prime and 32 positive intervals")
        raw_digest = observation["raw_log_sha256"]
        require(type(raw_digest) is str and qualification.historical.SHA256.fullmatch(raw_digest)
                and raw_digest not in seen, "qualified warm analysis reuses a raw transcript")
        seen.add(raw_digest)
        cycles = [row for row in observation["counter_deltas"] if row["name"] == "cycles"]
        require(len(cycles) == 1 and cycles[0]["available"] is True
                and type(cycles[0]["value"]) is int and 0 < cycles[0]["value"] < 2**64,
                "qualified warm analysis requires positive qualified batch cycles")
        total = sum(durations)
        batches.append({**planned, "build_qualification_id": build_ids[planned["format"]],
            "qualification_id": binding_id, "raw_log_sha256": raw_digest,
            "included_in_conditional_criteria": planned["phase"] == "measured",
            "timed_operations": warm.TIMED_OPERATIONS,
            "prime_duration_ns": all_durations[0],
            "operation_durations_ns": deepcopy(all_durations),
            "timed_total_ns": total, "batch_mean_ns": arithmetic._ratio(total, warm.TIMED_OPERATIONS),
            "reported_active_cycles": cycles[0]["value"],
            "reported_active_cycles_per_useful_flop": arithmetic._ratio(cycles[0]["value"], 16384),
            "reported_counter_deltas": deepcopy(observation["counter_deltas"]),
            "process_duration_seconds": process["process_duration_seconds"]})
    formats = [arithmetic._format_result(fmt, batches, contract, build_ids[fmt]) for fmt in warm.FORMATS]
    satisfied = all(row["conditional_criteria_satisfied"] for row in formats)
    return {"schema_version": 1, "contract_id": CONTRACT_ID,
        "scope": "frozen-predicates-after-complete-qualified-warm-reconstruction",
        "hypothesis_evaluation": "satisfied" if satisfied else "not_satisfied",
        "source_revision": expected_revision, "measurement_contract_sha256": qualification.WARM_CONTRACT_SHA256,
        "counts": deepcopy(contract["complete_matrix"]), "excluded_prime_operations": 24,
        "excluded_warmup_processes": [row["id"] for row in plan if row["phase"] == "warmup"],
        "batches": batches, "formats": formats,
        "criteria_arithmetic": "exact_integer_cross_products_of_batch_totals",
        "counter_scope": "qualified_modeled_cumulative_batch_observations",
        "native_execution": "not_run", "performance_acceptance": False,
        "phase_acceptance": False, "acceptance_claimed": False,
        "limitations": [
            "This internal arithmetic requires the complete qualified archive reader; its input dictionaries alone are not qualification evidence.",
            "Five paired batch means per format and policy are descriptive; separate processes do not prove statistical independence.",
            "Instrumented host time and modeled batch cycles are not physical GPU latency, throughput, power or energy.",
            "All samples and frozen predicates are retained, including an unsatisfied hypothesis; no phase acceptance is inferred.",
        ]}
