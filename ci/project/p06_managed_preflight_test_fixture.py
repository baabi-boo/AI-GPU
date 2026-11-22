# SPDX-License-Identifier: Apache-2.0
"""Synthetic managed-preflight logs; no native execution or timing evidence."""

from copy import deepcopy
import json

import p06_managed_preflight_contract as manifest
import p06_warm_contract as warm_contract
import p06_warm_test_fixture as warm_fixture


BINDING = warm_fixture.BINDING
EXPECTED_LIBRARIES = {
    "libramulator-vortex.so": "/producer/source/third_party/ramulator_ext/libramulator-vortex.so",
    "libramulator.so": "/producer/source/third_party/ramulator/libramulator.so",
    "libsimx.so": "/producer/build/sw/runtime/libsimx.so",
    "libvortex-simx.so": "/producer/build/sw/runtime/libvortex-simx.so",
    "libvortex.so": "/producer/build/sw/runtime/libvortex.so",
}


def _cp(expected):
    return {
        "control": 1, "queue_control": 1, "status": 0, "error": 0,
        "retired": expected, "expected": expected,
        "head_writeback_raw": 0, "head_writeback_status": "not-published",
        "runtime_tail": expected * 64, "tail_register_pair_raw": expected * 64,
        "drain_basis": "enabled-idle-status-and-retired-sequence",
    }


def raw_records(fmt="fp16", policy="per_operation", *, binding_id=BINDING,
                durations_ns=100, counter_deltas=None, contract=None):
    """Reuse independent numerical words and invent internally consistent observations."""
    contract = manifest.load_contract() if contract is None else contract
    manifest.validate_contract(contract)
    identity = manifest.process_identity(fmt, policy, binding_id)
    case, operations, summary = warm_fixture.raw_records(
        fmt, policy, pair_index=0, binding_id=binding_id, durations_ns=durations_ns,
        counter_deltas=counter_deltas, contract=warm_contract.load_contract())
    public_snapshots = summary["snapshots"]
    for ordinal, name in enumerate(manifest.SNAPSHOT_NAMES):
        for index, row in enumerate(public_snapshots[name]["counters"]):
            if row["enabled"]:
                if ordinal == 0:
                    row["value"] = 0
                elif ordinal == 3:
                    row["value"] = public_snapshots["after_batch"]["counters"][index]["value"]
                else:
                    row["value"] += 1 << 32

    snapshots, reads = [], []
    for ordinal, name in enumerate(manifest.SNAPSHOT_NAMES):
        enabled = [row for row in public_snapshots[name]["counters"] if row["enabled"]]
        values = {row["name"]: row["value"] for row in enabled}
        # Direct-RAM launches reset platform time; aggregate counters survive.
        ticks = (0 if ordinal == 0 else values["cycles"] + 97 if ordinal == 1
                 else values["cycles"] // 33 + 97)
        model = {
            "live": True, "idle": True, "any_running": False, "generation": 1,
            "ticks": ticks, "reset_generation": (1, 2, 34, 34)[ordinal],
            "core_cycles": values["cycles"], "core_instructions": values["instructions"],
            "exitcode": 0,
        }
        resident = policy == "reusable_single_tile" and ordinal in (1, 2)
        terminal = ordinal == 3
        snapshot = {
            "name": name, "before": deepcopy(model), "after": deepcopy(model),
            "read_begin": len(reads), "read_end": len(reads) + 66,
            "device_refs": 1 if terminal else 5 if resident else 2,
            "queues": 0, "buffers": 0 if terminal else 4 if resident else 1,
            "cache_flush_count": (0, 1, 33, 33)[ordinal],
            "cp_before": _cp(1024) if terminal else None,
            "cp_after": _cp(1090) if terminal else None,
        }
        snapshots.append(snapshot)
        for row in enabled:
            for high in (0, 1):
                offset = row["csr"] - 0xB00 + high * 32
                reads.append({
                    "sequence": len(reads) + 1 + (0, 1, 33, 33)[ordinal],
                    "completed_runs": (0, 1, 33, 33)[ordinal], "generation": 1, "addr": 0x001,
                    "tag": (row["mpm_class"] << 22) | (offset << 16) | row["core_id"],
                    "value": (row["value"] >> (high * 32)) & 0xFFFFFFFF,
                    "status": 0, "completed": True, "overflow": False,
                    "ticks_before": ticks, "ticks_after": ticks,
                    "reset_before": model["reset_generation"],
                    "reset_after": model["reset_generation"],
                    "class_before": 0, "class_after": 0,
                    "idle_before": True, "idle_after": True,
                    "any_running_before": False, "any_running_after": False,
                })

    cache_flush_reads = []
    for index in range(33):
        cache_flush_reads.append({
            "sequence": 67 if index == 0 else 133 + index,
            "generation": 1, "completed_runs": index + 1,
            "addr": 0, "tag": 0, "value": 0, "status": 0,
            "completed": True, "overflow": False,
            "ticks_before": 100, "ticks_after": 107,
            "reset_before": index + 2, "reset_after": index + 2,
            "class_before": 0, "class_after": 0,
            "idle_before": True, "idle_after": True,
            "any_running_before": False, "any_running_after": False,
        })
    observation = {
        "constructed": 1, "destroyed": 1, "constructor_entries": 1,
        "destructor_entries": 1, "run_entries": 33, "run_completed": 33,
        "run_errors": 0, "dcr_read_entries": 297, "dcr_read_completed": 297,
        "dcr_read_errors": 0, "dcr_write_entries": 172, "dcr_write_completed": 172,
        "dcr_write_errors": 0, "overflow_errors": 0, "underflow_errors": 0,
        "negative_operand_errors": 0, "unexpected_errors": 0, "violations": 0,
        "generation": 1, "read_count": 264, "cache_flush_count": 33, "live": False,
        "constructed_state": deepcopy(snapshots[0]["before"]),
        "destruction": {
            "before": deepcopy(snapshots[-1]["after"]), "completed": True,
            "ticks_after": 0, "reset_after": snapshots[-1]["after"]["reset_generation"],
            "idle_after": True,
        },
    }
    witness = {
        **identity, "backend": "simx", "xlen": 64, "checked_counter_bits": 64,
        "simulation_workers": 1, "seeded": False, "observation": observation,
        "snapshots": snapshots, "reads": reads, "cache_flush_reads": cache_flush_reads,
        "loaded_libraries": [{"name": name, "path": path}
                             for name, path in sorted(EXPECTED_LIBRARIES.items())],
        "unresolved_obligations": list(manifest.UNRESOLVED_OBLIGATIONS),
        **dict.fromkeys(manifest.FALSE_CLAIMS, False),
    }
    return case, operations, summary, witness


def render_log(operations, summary, witness):
    return (warm_fixture.render_log(operations, summary) + manifest.WITNESS_PREFIX
            + json.dumps(witness, separators=(",", ":"), allow_nan=False) + "\n")


def synthetic_log(*args, **kwargs):
    return render_log(*raw_records(*args, **kwargs)[1:])
