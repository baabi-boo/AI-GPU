# SPDX-License-Identifier: Apache-2.0
"""Coherent synthetic lifetime transcripts; no native execution or timing proof."""

from copy import deepcopy
import json

import p06_managed_preflight_test_fixture as parent_fixture
import p06_native_lifetime_contract as manifest


BINDING = parent_fixture.BINDING
EXPECTED_LIBRARIES = dict(parent_fixture.EXPECTED_LIBRARIES)


def _extended(value):
    return dict(value, pending_reads=0)


def raw_records(fmt="fp16", policy="per_operation", *, binding_id=BINDING,
                durations_ns=100, counter_deltas=None, contract=None):
    case, operations, summary, witness = parent_fixture.raw_records(
        fmt, policy, binding_id=binding_id, durations_ns=durations_ns,
        counter_deltas=counter_deltas, contract=contract)
    snapshots = witness["snapshots"]
    opening = snapshots[0]["before"]
    prime, final = (snapshots[index]["before"] for index in (1, 2))
    baseline = opening["reset_generation"]
    previous = _extended(opening)
    runs = []
    endpoint_states = {0: deepcopy(opening)}
    for index in range(manifest.OPERATIONS):
        ordinal = index + 1
        after = dict(previous, reset_generation=baseline + ordinal)
        for name in ("core_cycles", "core_instructions"):
            after[name] = prime[name] + (final[name] - prime[name]) * index // 32
        after["ticks"] = after["core_cycles"] - previous["core_cycles"] + 97
        reads = 66 if ordinal == 1 else 131 + ordinal
        runs.append({
            "ordinal": ordinal, "before": deepcopy(previous), "after": deepcopy(after),
            **manifest.SUCCESSFUL_RUN, "dcr_reads_before": reads, "dcr_reads_after": reads,
            "cache_flushes_before": index, "cache_flushes_after": index,
        })
        flush = witness["cache_flush_reads"][index]
        flush.update(ticks_before=after["ticks"], ticks_after=after["ticks"] + 7,
                     reset_before=baseline + ordinal, reset_after=baseline + ordinal)
        previous = dict(after, ticks=flush["ticks_after"])
        if ordinal in (1, manifest.OPERATIONS):
            endpoint_states[1 if ordinal == 1 else 2] = {
                name: previous[name] for name in parent_fixture.manifest.MODEL_FIELDS}
    endpoint_states[3] = deepcopy(endpoint_states[2])
    for index, snapshot in enumerate(snapshots):
        snapshot["before"] = deepcopy(endpoint_states[index])
        snapshot["after"] = deepcopy(endpoint_states[index])
        for read in witness["reads"][snapshot["read_begin"]:snapshot["read_end"]]:
            read.update(ticks_before=endpoint_states[index]["ticks"],
                        ticks_after=endpoint_states[index]["ticks"],
                        reset_before=endpoint_states[index]["reset_generation"],
                        reset_after=endpoint_states[index]["reset_generation"])
    observation = witness["observation"]
    observation["constructed_state"] = deepcopy(endpoint_states[0])
    observation["destruction"]["before"] = deepcopy(endpoint_states[3])
    observation["destruction"]["reset_after"] = endpoint_states[3]["reset_generation"]
    destruction = deepcopy(observation["destruction"])
    destruction["before"] = _extended(destruction["before"])
    lifetime = {
        **manifest.process_identity(fmt, policy, binding_id), **manifest.ROUTE,
        "constructed_state": _extended(observation["constructed_state"]),
        "runs": runs,
        "snapshots": [{"name": row["name"], "before": _extended(row["before"]),
                       "after": _extended(row["after"])} for row in snapshots],
        "reads": [{"sequence": row["sequence"], "pending_before": 0, "pending_after": 0}
                  for row in witness["reads"]],
        "cache_flush_reads": [
            {"sequence": row["sequence"], "pending_before": 0, "pending_after": 0}
            for row in witness["cache_flush_reads"]],
        "destruction": destruction, "trace_overflow": False,
        "unresolved_obligations": list(manifest.UNRESOLVED_OBLIGATIONS),
        **dict.fromkeys(manifest.FALSE_CLAIMS, False),
    }
    return case, operations, summary, witness, lifetime


def render_log(operations, summary, witness, lifetime):
    return (parent_fixture.render_log(operations, summary, witness) + manifest.WITNESS_PREFIX
            + json.dumps(lifetime, separators=(",", ":"), allow_nan=False) + "\n")


def synthetic_log(*args, **kwargs):
    return render_log(*raw_records(*args, **kwargs)[1:])
