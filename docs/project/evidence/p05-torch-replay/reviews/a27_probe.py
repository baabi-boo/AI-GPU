#!/usr/bin/env python3
"""Focused synthetic raw-log probe; no archive, framework, or GPU execution."""

import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1] / "AI-GPU"
sys.path.insert(0, str(ROOT / "ci/project"))

import p05_execution_records as base
import p05_torch_records as torch
import p05_replay_native as native
from p05_qualification_test_fixture import raw_log as base_log
from p05_torch_qualification_test_fixture import raw_log as torch_log, synthetic
from test_p05_retained_observation_records import retained_identity, denied_live_access
from test_p05_replay_native import (
    MemoryView, synthetic_results, MODEL_ID, MATMUL_ID, REVISION,
    matmul_output, model_output,
)

SOURCES = (
    "ci/project/p05_execution_records.py", "ci/project/p05_torch_records.py",
    "ci/project/p05_replay_native.py", "ci/project/p03_execution_records.py",
    "ci/project/p04_execution_records.py", "ci/project/p05_torch_replay.py",
    "docs/project/evidence/p05-torch/reviews/archive_reader.py",
    *("ci/project/fixtures/" + name for name in native.FIXTURES),
)
COUNTS = {"matmul_runs": 6, "model_runs": 10, "matmul_launches": 6,
          "model_launches": 30, "total_launches": 36}
outcomes = []


def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES}


def check(label, callback, rejection=None):
    with denied_live_access():
        try:
            result = callback()
        except ValueError as error:
            if rejection is None or rejection not in str(error):
                raise AssertionError((label, rejection, str(error))) from error
            outcomes.append({"check": label, "outcome": "rejected", "reason": str(error)})
        else:
            if rejection is not None:
                raise AssertionError(label + " unexpectedly accepted")
            counts = result[2] if type(result) is tuple else result["counts"]
            assert counts == COUNTS, (label, counts)
            outcomes.append({"check": label, "outcome": "accepted", "counts": counts})


def native_check(sample):
    files, report, python, matmuls, models = sample
    view = MemoryView(files)
    return native._results(view.subview("native"), view.subview("python"), report,
                           python, matmuls, models, MODEL_ID, MATMUL_ID, REVISION, "fp16")


before = hashes()
with tempfile.TemporaryDirectory(prefix="a27-synthetic-") as directory:
    value, request, comparisons = synthetic(Path(directory))
    identity = retained_identity(value, request)
    adapter = Path(value["framework"]["adapter_file"]).read_bytes()
    shutil.rmtree(directory)
    original_base = value["base_observations"]

    def verify_base(observed, raw):
        return base.verify_retained_observations(observed, request["base_request"],
            retained_identity=identity, **comparisons, raw_log=raw)

    def verify_torch(observed, raw):
        return torch.verify_retained_observations(observed, request,
            retained_identity=identity, adapter_bytes=adapter, **comparisons, raw_log=raw)

    for kind, observed, make_log, verify in (
        ("base", original_base, base_log, verify_base),
        ("torch", value, torch_log, verify_torch),
    ):
        raw = make_log(observed)
        check(kind + ":valid", lambda: verify(observed, raw))
        lines = raw.splitlines(keepends=True)
        marker_index = 0 if kind == "base" else 2
        duplicated = "".join(lines[:marker_index] + [lines[marker_index]] + lines[marker_index:])
        check(kind + ":identical_duplicate", lambda: verify(observed, duplicated),
              "raw log" if kind == "base" else "chronology")
        missing = "".join(lines[:-1])
        check(kind + ":missing_final_row", lambda: verify(observed, missing),
              "raw log" if kind == "base" else "chronology")
        failure = 'P05_FAILURE {"error_type":"CheckError","error":"synthetic final cleanup","cleanup_complete":false}\n'
        check(kind + ":late_structured_failure", lambda: verify(observed, raw + failure), "contains a failure")
        changed = copy.deepcopy(observed)
        data = changed if kind == "base" else changed["base_observations"]
        data["matmuls"][:2] = reversed(data["matmuls"][:2])
        if kind == "torch":
            changed["framework_matmuls"][:2] = reversed(changed["framework_matmuls"][:2])
        check(kind + ":coherent_iteration_reorder", lambda: verify(changed, make_log(changed)),
              "membership/order")
        oversized = "x" * (base.MAX_JSON_BYTES + 1)
        check(kind + ":log_over_16MiB", lambda: verify(observed, oversized), "oversized")
        del oversized

sample = synthetic_results()
check("native:valid_matmul_and_model", lambda: native_check(sample))
for kind in ("matmul", "model"):
    for attack in ("identical_duplicate", "missing_final_row", "coherent_iteration_reorder",
                   "late_failure_after_PASSED", "log_over_16MiB"):
        changed = copy.deepcopy(sample)
        case = (changed[2]["native_matmuls"] if kind == "matmul"
                else changed[1]["variants"][0]["cases"])[0]
        path = ("python/logs/native-" if kind == "matmul" else "native/logs/simx-fp16-") + case["id"] + ".log"
        rows = case["observations"]
        output = matmul_output if kind == "matmul" else model_output
        if attack == "identical_duplicate":
            rows.insert(1, copy.deepcopy(rows[0]))
            reason = "reordered result" if kind == "matmul" else "repetition order"
        elif attack == "missing_final_row":
            rows.pop()
            reason = "missing or extra operator launches" if kind == "matmul" else "missing model repetition"
        elif attack == "coherent_iteration_reorder":
            rows.reverse()
            reason = "reordered result" if kind == "matmul" else "repetition order"
        changed[0][path] = output(rows).encode()
        if attack == "late_failure_after_PASSED":
            failure = (b"FAILED managed matmul, exit=6\n" if kind == "matmul" else
                       b"P04_FAILURE " + json.dumps(rows[-1], separators=(",", ":")).encode() + b"\n")
            changed[0][path] += failure
            reason = "contains a failure"
        elif attack == "log_over_16MiB":
            changed[0][path] = b"x" * (native.MAX_LOG_BYTES + 1)
            reason = "member exceeds bound"
        check("native_" + kind + ":" + attack, lambda: native_check(changed), reason)

changed = copy.deepcopy(sample)
case = changed[1]["variants"][0]["cases"][0]
path = "native/logs/simx-fp16-" + case["id"] + ".log"
lines = changed[0][path].splitlines(keepends=True)
index = next(i for i, line in enumerate(lines) if line.startswith(b"P04_RESULT "))
line = lines[index].rstrip(b"\n")
payload_bytes = len(line) - len(b"P04_RESULT ")
lines[index] = line + b" " * (256 * 1024 + 1 - payload_bytes) + b"\n"
changed[0][path] = b"".join(lines)
check("native_model:record_over_256KiB", lambda: native_check(changed), "record exceeds its byte bound")

after = hashes()
assert before == after, "reviewed source or frozen numerical fixture changed during probe"
print(json.dumps({"scope": "synthetic fp16 raw-log seams; not full archive replay or native execution",
    "checks": len(outcomes), "accepted_controls": sum(row["outcome"] == "accepted" for row in outcomes),
    "rejected_attacks": sum(row["outcome"] == "rejected" for row in outcomes),
    "source_and_fixture_hashes_stable": before == after, "sha256": after,
    "outcomes": outcomes}, indent=2, sort_keys=True))
