# SPDX-License-Identifier: Apache-2.0
"""Synthetic host-test inputs only; these helpers never execute a GPU."""

from copy import deepcopy
from functools import lru_cache
import json

import p02_wmma_fixtures
import p04_fixture_adapter
import p06_contract
import p06_records
from test_p03_execution_records import result as operator_result
from test_p04_execution_records import result as model_result


BINDING = "0123456789abcdef" * 4
REVISION = "1234567890abcdef" * 2 + "12345678"
COUNTER_FIELDS = ("name", "mpm_class", "csr", "core_id", "scope", "unit", "required_isa")


@lru_cache(maxsize=1)
def _cases():
    return {
        "matmul": {case["id"]: case for case in p02_wmma_fixtures.load_cases()},
        "mlp": {case["id"]: case for case in p04_fixture_adapter.load_cases()},
    }


def raw_records(workload, sample_id, *, contract=None, binding_id=BINDING,
                source_revision=REVISION, delta=1000):
    contract = p06_contract.load_contract() if contract is None else contract
    before = {
        "schema_version": 1, "sample_id": sample_id, "context_id": 1,
        "device_index": 0, "compiled_memory_block_bytes": 64,
        "query_begin_ns": 150, "query_end_ns": 155,
        "capabilities": [{**descriptor, "status": 0,
                          "value": contract["capability_values"][descriptor["name"]]}
                         for descriptor in contract["capabilities"]],
        "counters": [],
    }
    isa = contract["capability_values"]["isa_flags"]
    for index, descriptor in enumerate(contract["counters"]):
        required = descriptor["required_isa"]
        enabled = required == 0 or isa & required == required
        before["counters"].append({
            **{key: descriptor[key] for key in COUNTER_FIELDS},
            "enabled": enabled, "status": 0 if enabled else None,
            "value": (1 << 63) + 100 + index if enabled else None,
        })
    after = deepcopy(before)
    after.update(query_begin_ns=4000, query_end_ns=4005)
    for counter in after["counters"]:
        if counter["enabled"]:
            counter["value"] += delta
    release = {"schema_version": 1, "sample_id": sample_id, "context_id": 1, "status": 0}
    case = _cases()[workload["kind"]][workload["case_id"]]
    if workload["kind"] == "matmul":
        numerical = operator_result(case, iteration=0)
        marker = "P03_RESULT"
    else:
        numerical = model_result(case, iteration=0, backend="simx")
        numerical["trace"]["advance_ns"] = 3500
        numerical["source_revision"] = source_revision
        numerical["fixture_sha256"] = workload["fixture_sha256"]
        for stage in numerical["trace"]["native"]:
            stage["dispatch"]["qualification_id"] = binding_id
        marker = "P04_RESULT"
    numerical["qualification_id"] = binding_id
    return {"P06_BEGIN": before, "P06_END": after, "P06_RELEASE": release, marker: numerical}


def render_log(workload, raw):
    if workload["kind"] == "matmul":
        order = ("P06_BEGIN", "P03_REJECTIONS checked=2", "P03_RESULT", "P06_END", "P06_RELEASE")
    else:
        order = ("P06_BEGIN", "P06_END", "P06_RELEASE", "P04_RESULT")
    lines = ["synthetic host-test observation; no native execution"]
    for marker in order:
        lines.append(marker if marker.startswith("P03_REJECTIONS") else
                     marker + " " + json.dumps(raw[marker], separators=(",", ":")))
    return "\n".join((*lines, "PASSED!", ""))


def synthetic_log(workload, sample_id, *, contract=None, binding_id=BINDING,
                  source_revision=REVISION, delta=1000):
    return render_log(workload, raw_records(workload, sample_id, contract=contract,
                      binding_id=binding_id, source_revision=source_revision, delta=delta))


def sample(workload, phase, repetition, *, contract=None, binding_id=BINDING,
           source_revision=REVISION, duration=1.0, delta=1000):
    contract = p06_contract.load_contract() if contract is None else contract
    sample_id = workload["id"] + "-" + phase + "-" + str(repetition)
    text = synthetic_log(workload, sample_id, contract=contract, binding_id=binding_id,
                         source_revision=source_revision, delta=delta)
    return {
        "sample_id": sample_id, "workload_id": workload["id"], "phase": phase,
        "repetition": repetition, "command_id": "simx-" + sample_id,
        "outcome": "pass", "process_duration_seconds": duration,
        "observation": p06_records.verify_sample(text, workload, binding_id, sample_id=sample_id,
                        source_revision=source_revision, fixture_sha256=workload["fixture_sha256"],
                        contract=contract),
    }


def samples(contract=None, formats=None):
    contract = p06_contract.load_contract() if contract is None else contract
    rows = []
    for workload in p06_contract.select_workloads(contract, formats):
        rows.append(sample(workload, "warmup", 0, contract=contract, duration=90.0, delta=999999))
        for repetition, delta in enumerate((1000, 1200, 900, 1300, 1100)):
            rows.append(sample(workload, "measurement", repetition, contract=contract,
                               duration=1.0 + repetition / 10, delta=delta))
    return rows
