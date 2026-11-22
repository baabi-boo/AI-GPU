# SPDX-License-Identifier: Apache-2.0
"""Validate complete warm-workspace native logs without executing retained code."""

from __future__ import annotations

import hashlib
import re

import p06_records as counters
import p06_warm_contract as manifest
import p06_workspace_records as workspace


ROOT = manifest.ROOT
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_RECORD_BYTES = 256 * 1024
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
HEX_WORD = re.compile(r"[0-9a-f]{8}\Z")
require = manifest.require
_keys = workspace._keys
_same = manifest._same
_uint = workspace._uint


def _identity(row, expected, label):
    for key in manifest.IDENTITY_KEYS:
        _same(row[key], expected[key], label + "." + key)


def _inputs(case, fmt, policy, binding_id, sample_id, pair_index, phase, contract):
    manifest.validate_contract(contract, ROOT)
    require(type(fmt) is str and fmt in manifest.FORMATS, "unsupported warm format")
    require(type(policy) is str and policy in manifest.POLICIES, "unsupported warm policy")
    require(type(binding_id) is str and SHA256.fullmatch(binding_id) is not None,
            "warm execution binding must be lowercase SHA-256")
    require(type(pair_index) is int and 0 <= pair_index <= 5,
            "warm pair index must be an integer from zero through five")
    expected_sample = f"warm-simx-{fmt}-pair{pair_index}-{policy}"
    _same(sample_id, expected_sample, "warm sample identity")
    _same(phase, "warmup" if pair_index == 0 else "measured", "warm sample phase")
    selected = manifest.select_cases(contract, ROOT, [fmt])
    require(len(selected) == 1, "warm fixture selection is incomplete")
    _same(case, selected[0], "warm independent fixture")
    return {"schema_version": 1, "contract_id": manifest.CONTRACT_ID,
            "qualification_id": binding_id, "sample_id": sample_id,
            "format": fmt, "policy": policy, "pair_index": pair_index, "phase": phase}


def _records(text, contract):
    workspace._text(text, MAX_OUTPUT_BYTES, "warm native output")
    require(not re.search(r"\b(?:FAILED|FAIL|ERROR|FATAL|ABORTED|MISMATCH)\b|"
                          r"Assertion .*failed|Segmentation fault|core dumped|runtime error:",
                          text, re.IGNORECASE), "warm native output contains a failure marker")
    lines = text.splitlines()
    observation = contract["observation"]
    success = observation["success_marker"]
    require(lines and lines[-1] == success and lines.count(success) == 1
            and len(re.findall(r"\bPASSED!", text, re.IGNORECASE)) == 1,
            "warm output requires exactly one final success marker")
    operation_prefix = observation["operation_marker"] + " "
    summary_prefix = observation["summary_marker"] + " "
    operations, summary = [], None
    for index, line in enumerate(lines[:-1]):
        require(len(line.encode("utf-8")) <= MAX_RECORD_BYTES,
                "warm output line exceeds its byte bound")
        if line.startswith(operation_prefix):
            require(summary is None and len(operations) < manifest.OPERATIONS,
                    "warm operation follows summary or exceeds the fixed sequence")
            operations.append(counters._json(line[len(operation_prefix):]))
        elif line.startswith(summary_prefix):
            require(summary is None and len(operations) == manifest.OPERATIONS,
                    "warm summary is repeated or precedes the complete sequence")
            require(index == len(lines) - 2, "warm summary must immediately precede success")
            summary = counters._json(line[len(summary_prefix):])
        else:
            require(not re.search(r"P0[3456]|\bPASSED\b", line, re.IGNORECASE),
                    "unknown, malformed or wrong-route warm record marker")
    require(len(operations) == manifest.OPERATIONS and summary is not None,
            "warm output lacks the complete operation/summary inventory")
    return operations, summary


def _operation(row, case, index, identity):
    label = "warm operation " + str(index)
    _keys(row, manifest.OPERATION_KEYS, label)
    _identity(row, identity, label)
    for key, expected in (
            ("operation_index", index), ("role", "prime" if index == 0 else "sample"),
            ("case_id", case["id"]), ("m", 8), ("n", 4), ("k", 8),
            ("poison", manifest.poison_for(index)), ("checked", 32),
            ("mismatches", 0), ("passed", True)):
        _same(row[key], expected, label + "." + key)
    begin = _uint(row["begin_ns"], label + ".begin_ns")
    end = _uint(row["end_ns"], label + ".end_ns")
    require(begin < end, label + " requires a positive host interval")
    bits = row["actual_bits"]
    require(type(bits) is list and len(bits) == 32
            and all(type(word) is str and HEX_WORD.fullmatch(word) is not None for word in bits),
            label + " requires exactly 32 lowercase hexadecimal FP32 words")
    _same(bits, case["expected"], label + ".actual_bits")
    addresses = workspace._dispatch(row["dispatch"], identity["format"], label + ".dispatch")
    _keys(row["results"], ("submit", "wait", "close"), label + ".results")
    for name in ("submit", "wait", "close"):
        workspace._result(row["results"][name], label + "." + name, complete=name != "submit")
    resident = identity["policy"] == "reusable_single_tile"
    before = workspace._expected_counts(3 if resident else 3 * index,
        0 if resident else 3 * index, resident, 320 if resident or index else 0)
    after = workspace._expected_counts(3 if resident else 3 * (index + 1),
        0 if resident else 3 * (index + 1), resident, 320)
    workspace._counts(row["counts_before"], before, label + ".counts_before")
    workspace._counts(row["counts_after"], after, label + ".counts_after")
    return addresses


def _memory(value, label):
    _keys(value, manifest.MEMORY_KEYS, label)
    _same(value["queried"], True, label + ".queried")
    _same(value["status"], 0, label + ".status")
    total = sum(_uint(value[key], label + "." + key) for key in ("free_bytes", "used_bytes"))
    require(0 < total <= manifest.MAX_UINT64, label + " has an invalid memory capacity")
    return total


def _resources(summary, identity):
    resident = identity["policy"] == "reusable_single_tile"
    total = 3 if resident else 99
    workspace._counts(summary["counts"],
        workspace._expected_counts(total, total, False, 320, device_releases=1),
        "warm final counts")
    memory = summary["memory"]
    _keys(memory, manifest.MEMORY_NAMES, "warm memory")
    capacities = [_memory(memory[name], "warm memory." + name) for name in manifest.MEMORY_NAMES]
    require(len(set(capacities)) == 1, "warm memory capacity changed between observations")
    for name in ("after_prime", "after_batch"):
        _same(memory[name], memory["after_create"], "warm idle memory." + name)
    _same(memory["before_release"], memory["after_open"], "warm final memory restoration")
    require(memory["after_create"]["used_bytes"] >= memory["after_open"]["used_bytes"]
            + (320 if resident else 0), "warm context accounting lacks its retained tensor payload")


def _interval(value, label):
    _keys(value, ("begin_ns", "end_ns"), label)
    begin, end = (_uint(value[key], label + "." + key) for key in ("begin_ns", "end_ns"))
    require(begin <= end, label + " is reversed")
    return begin, end


def _snapshots(summary, operations, identity, contract):
    snapshots = summary["snapshots"]
    _keys(snapshots, manifest.SNAPSHOT_NAMES, "warm counter snapshots")
    for name in manifest.SNAPSHOT_NAMES:
        counters._snapshot(snapshots[name], sample_id=identity["sample_id"],
                           contract=contract, label="warm " + name)
    intervals = summary["host_intervals_ns"]
    _keys(intervals, ("create", "close"), "warm host intervals")
    create_begin, create_end = _interval(intervals["create"], "warm context creation")
    close_begin, close_end = _interval(intervals["close"], "warm context teardown")
    opened, primed, batched, releasing = (snapshots[name] for name in manifest.SNAPSHOT_NAMES)
    require(create_begin <= opened["query_begin_ns"] <= opened["query_end_ns"] <= create_end,
            "warm open snapshot lies outside context creation")
    require(create_end <= operations[0]["begin_ns"]
            and operations[0]["end_ns"] <= primed["query_begin_ns"]
            and primed["query_end_ns"] <= operations[1]["begin_ns"],
            "warm prime/snapshot/sample chronology differs")
    require(all(first["end_ns"] <= last["begin_ns"]
                for first, last in zip(operations, operations[1:])),
            "warm primary operation intervals overlap or are reordered")
    require(operations[-1]["end_ns"] <= batched["query_begin_ns"]
            and batched["query_end_ns"] <= close_begin
            and close_begin <= releasing["query_begin_ns"]
            and releasing["query_end_ns"] <= close_end,
            "warm batch/snapshot/teardown chronology differs")
    for first_name, last_name in zip(manifest.SNAPSHOT_NAMES, manifest.SNAPSHOT_NAMES[1:]):
        for first, last in zip(snapshots[first_name]["counters"], snapshots[last_name]["counters"]):
            if first["enabled"]:
                require(last["value"] >= first["value"],
                        "warm cumulative counter decreased or wrapped: " + first["name"])
    _same(summary["device_release"], {"schema_version": 1, "sample_id": identity["sample_id"],
             "context_id": 1, "status": 0}, "warm actual device release")
    return counters._lifetime({"begin": primed, "end": batched}, summary["device_release"],
                               sample_id=identity["sample_id"], contract=contract)


def verify_output(text, *, case, fmt, policy, binding_id, sample_id, pair_index, phase, contract):
    """Validate one complete primed policy batch; no matrix or speedup is accepted."""
    identity = _inputs(case, fmt, policy, binding_id, sample_id, pair_index, phase, contract)
    operations, summary = _records(text, contract)
    resident_addresses = None
    for index, row in enumerate(operations):
        addresses = _operation(row, case, index, identity)
        if policy == "reusable_single_tile":
            if resident_addresses is None:
                resident_addresses = addresses
            _same(addresses, resident_addresses, "warm resident addresses")
    _keys(summary, manifest.SUMMARY_KEYS, "warm summary")
    _identity(summary, identity, "warm summary")
    for key, expected in (("operations", 33), ("checked", 1056), ("mismatches", 0), ("passed", True)):
        _same(summary[key], expected, "warm summary." + key)
    _keys(summary["results"], ("create", "close"), "warm owner results")
    for name in ("create", "close"):
        workspace._result(summary["results"][name], "warm owner." + name)
    _resources(summary, identity)
    deltas = _snapshots(summary, operations, identity, contract)
    durations = [row["end_ns"] - row["begin_ns"] for row in operations]
    return {**identity, "raw_log_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "operations": operations, "summary": summary,
            "operation_durations_ns": durations, "timed_operation_durations_ns": durations[1:],
            "counter_deltas": deltas,
            "accounting": {"launches": 33, "checked_words": 1056, "timed_operations": 32,
                           "timed_useful_flops": 16384, "input_h2d_bytes": 33 * 192,
                           "poison_h2d_bytes": 33 * 128, "tensor_d2h_bytes": 33 * 128},
            "performance_acceptance": False, "phase_acceptance": False}
