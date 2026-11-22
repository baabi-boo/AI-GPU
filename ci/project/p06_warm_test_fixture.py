# SPDX-License-Identifier: Apache-2.0
"""Synthetic warm records for host tests; no native execution or timing evidence."""

from copy import deepcopy
import json

import p06_warm_contract as manifest


BINDING = "0123456789abcdef" * 4


def argument_hex(fmt, addresses):
    words = (1, 56, 1 if fmt == "fp16" else 2, 0, 8, 4, 8, 0)
    return (b"".join(value.to_bytes(4, "little") for value in words)
            + b"".join(value.to_bytes(8, "little") for value in addresses)).hex()


def _result(complete=True):
    return {"validation": 0, "primary": 0, "cleanup": 0, "complete": complete}


def _counts(creates, releases, resident=False, *, peak=320, closed=False):
    return {"device_open_calls": 1, "device_release_calls": int(closed),
            "buffer_create_calls": creates, "buffer_release_calls": releases,
            "live_buffers": 3 if resident else 0,
            "live_requested_bytes": 320 if resident else 0,
            "peak_requested_payload_bytes": peak, "premature_releases": 0, "errors": 0}


def raw_records(fmt="fp16", policy="per_operation", *, pair_index=1, binding_id=BINDING,
                durations_ns=100, counter_deltas=None, contract=None, start_ns=1000):
    """Return independent fixture words with invented observations for one batch."""
    contract = manifest.load_contract() if contract is None else contract
    if fmt not in manifest.FORMATS or policy not in manifest.POLICIES:
        raise ValueError("unsupported synthetic warm format or policy")
    if type(pair_index) is not int or not 0 <= pair_index <= 5:
        raise ValueError("synthetic warm pair must be zero through five")
    if type(start_ns) is not int or start_ns < 100:
        raise ValueError("synthetic start must leave room for owner creation")
    durations = ([durations_ns] * 33 if type(durations_ns) is int
                 else list(durations_ns) if type(durations_ns) in (tuple, list) else [])
    if len(durations) != 33 or any(type(value) is not int or value <= 0 for value in durations):
        raise ValueError("synthetic warm timing requires 33 positive integer intervals")
    deltas = {} if counter_deltas is None else dict(counter_deltas)
    isa = contract["capability_values"]["isa_flags"]
    enabled_names = {row["name"] for row in contract["counters"]
                     if row["required_isa"] == 0 or isa & row["required_isa"] == row["required_isa"]}
    if not set(deltas) <= enabled_names or any(type(value) is not int or value < 0 for value in deltas.values()):
        raise ValueError("synthetic counter deltas require available names and unsigned integers")
    case = deepcopy(manifest.select_cases(contract, formats=[fmt])[0])
    identity = {"schema_version": 1, "contract_id": manifest.CONTRACT_ID,
                "qualification_id": binding_id,
                "sample_id": f"warm-simx-{fmt}-pair{pair_index}-{policy}",
                "format": fmt, "policy": policy, "pair_index": pair_index,
                "phase": "warmup" if pair_index == 0 else "measured"}
    resident = policy == "reusable_single_tile"
    operations = []
    begin = start_ns
    for index, duration in enumerate(durations):
        addresses = [0x10000 + (0 if resident else index * 0x1000) + slot * 0x100
                     for slot in range(3)]
        creates_before = 3 if resident else index * 3
        creates_after = 3 if resident else (index + 1) * 3
        operations.append({**identity, "operation_index": index,
            "role": "prime" if index == 0 else "sample", "case_id": case["id"],
            "m": 8, "n": 4, "k": 8, "poison": 0xDEADBEEF if index % 2 == 0 else 0x7FC0DEAD,
            "begin_ns": begin, "end_ns": begin + duration,
            "checked": 32, "mismatches": 0, "actual_bits": deepcopy(case["expected"]),
            "passed": True,
            "dispatch": {"a_address": addresses[0], "b_address": addresses[1], "d_address": addresses[2],
                         "a_bytes": 128, "b_bytes": 64, "d_bytes": 128,
                         "writes": 3, "launches": 1, "reads": 1, "waits": 1, "timed_out_waits": 0,
                         "argument_bytes": argument_hex(fmt, addresses),
                         "event_results": [0] * 5, "profiling_enabled": False},
            "results": {"submit": _result(False), "wait": _result(), "close": _result()},
            "counts_before": _counts(creates_before, 0 if resident else creates_before,
                                     resident, peak=320 if resident or index else 0),
            "counts_after": _counts(creates_after, 0 if resident else creates_after, resident)})
        begin += duration + (30 if index == 0 else 10)
    prime_end = operations[0]["end_ns"]
    batch_end = operations[-1]["end_ns"]
    snapshot_times = {"after_open": (20, 30), "after_prime": (prime_end + 5, prime_end + 10),
                      "after_batch": (batch_end + 5, batch_end + 10),
                      "before_release": (batch_end + 30, batch_end + 35)}
    snapshots = {}
    for step, (name, (query_begin, query_end)) in enumerate(snapshot_times.items()):
        rows = []
        for index, descriptor in enumerate(contract["counters"]):
            enabled = descriptor["name"] in enabled_names
            delta = deltas.get(descriptor["name"], 1000)
            value = index + (0 if step == 0 else 1000 if step == 1
                             else 1000 + delta if step == 2 else 2000 + delta)
            rows.append({**{key: descriptor[key] for key in
                ("name", "mpm_class", "csr", "core_id", "scope", "unit", "required_isa")},
                "enabled": enabled, "status": 0 if enabled else None, "value": value if enabled else None})
        snapshots[name] = {"schema_version": 1, "sample_id": identity["sample_id"],
            "context_id": 1, "device_index": 0, "compiled_memory_block_bytes": 64,
            "query_begin_ns": query_begin, "query_end_ns": query_end,
            "capabilities": [{**descriptor, "status": 0,
                              "value": contract["capability_values"][descriptor["name"]]}
                             for descriptor in contract["capabilities"]], "counters": rows}
    memory = {}
    for name in manifest.MEMORY_NAMES:
        used = 256 if name in ("after_open", "before_release") else 832 if resident else 512
        memory[name] = {"queried": True, "status": 0, "free_bytes": (1 << 20) - used, "used_bytes": used}
    total = 3 if resident else 99
    summary = {**identity, "operations": 33, "checked": 1056, "mismatches": 0, "passed": True,
        "counts": _counts(total, total, closed=True), "snapshots": snapshots, "memory": memory,
        "results": {"create": _result(), "close": _result()},
        "host_intervals_ns": {"create": {"begin_ns": 10, "end_ns": 50},
                              "close": {"begin_ns": batch_end + 20, "end_ns": batch_end + 40}},
        "device_release": {"schema_version": 1, "sample_id": identity["sample_id"], "context_id": 1, "status": 0}}
    return case, operations, summary


def render_log(operations, summary):
    rows = ["Synthetic host-test records; no native execution"]
    rows.extend("P06_WARM_OPERATION " + json.dumps(row, separators=(",", ":")) for row in operations)
    rows.extend(("P06_WARM_SUMMARY " + json.dumps(summary, separators=(",", ":")), "PASSED!", ""))
    return "\n".join(rows)


def synthetic_log(*args, **kwargs):
    _, operations, summary = raw_records(*args, **kwargs)
    return render_log(operations, summary)
