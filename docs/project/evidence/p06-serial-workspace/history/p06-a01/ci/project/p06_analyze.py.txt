#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Analyze the complete P06 matrix from two digest-pinned original archives.

Both formats undergo trusted retained-data replay before any aggregation. This
reader never executes archived code, authenticates GitHub origin, grants phase
acceptance, or converts modeled counters into physical performance.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

import p06_replay as replay
from p06_contract import load_contract, select_workloads
from p06_records import summarize


ROOT = Path(__file__).resolve().parents[2]
SCOPE = "p06-full-matrix-retained-data-analysis"
METRICS = {
    "active_cycles_per_useful_flop": {
        "unit": "active_core_cycles_per_flop",
        "definition": "whole-context modeled active core cycles / logical useful FLOPs",
    },
    "retired_macroinstructions_per_mac": {
        "unit": "retired_macroinstructions_per_mac",
        "definition": "whole-context retired macroinstructions / logical multiply-accumulates",
    },
    "logical_tensor_bytes": {
        "unit": "bytes",
        "definition": "input H2D + destination-poison H2D + tensor D2H payload bytes",
    },
    "modeled_external_read_request_bytes": {
        "unit": "modeled_request_bytes",
        "definition": "modeled external read requests * checked compiled memory-block bytes",
    },
    "modeled_external_write_request_bytes": {
        "unit": "modeled_request_bytes",
        "definition": "modeled external write requests * checked compiled memory-block bytes",
    },
    "useful_flops_per_logical_tensor_byte": {
        "unit": "flops_per_payload_byte",
        "definition": "logical useful FLOPs / explicit tensor payload bytes including poison",
    },
}
LIMITATIONS = [
    "This is analysis of prior retained data, not a new native execution, acceptance decision, or optimization result.",
    "External ZIP digests and source revision bind the inputs; separate GitHub-origin and source-to-Git review remain required.",
    "Whole-context active cycles and macroinstructions cannot be assigned to individual kernels or model stages.",
    "Simulated cycles and modeled request bytes are not physical time, bandwidth, power, energy, or host DMA traffic.",
    "Logical payload bytes exclude module and control traffic; their arithmetic ratio is not a memory-controller roofline intensity.",
    "All warm-ups are validated and retained, but only the five measured samples contribute to descriptive statistics.",
    "Each invocation has a fresh process and device context; this experiment does not establish warm-cache or steady-state reuse.",
    "Host process duration includes supervisor, startup, validation, instrumentation and cleanup overhead; polling may delay observing exit.",
    "Host and event intervals may overlap. No observer time is subtracted, no overlapping durations are summed, and no polling delay is corrected retrospectively.",
    "Five measured samples establish neither confidence intervals nor production tail latency; all samples and outliers are preserved.",
    "Diagnostics do not identify a causal bottleneck. P06-A02/A03 and vendor, RTL, synthesis, FPGA and silicon obligations remain separate.",
]


class AnalysisError(ValueError):
    """The two original packets cannot support one complete baseline analysis."""


def _require(condition, message):
    if not condition:
        raise AnalysisError(message)


def _same(actual, expected, label):
    try:
        replay._same(actual, expected, label)
    except replay.ReplayError as error:
        raise AnalysisError(str(error)) from error


def _identity(value):
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _source_identity():
    path = Path(__file__).resolve()
    _require(path == ROOT / "ci/project/p06_analyze.py", "analyzer is not loaded from the trusted repository")
    body = path.read_bytes()
    return {"path": "ci/project/p06_analyze.py", "sha256": hashlib.sha256(body).hexdigest(),
            "size_bytes": len(body)}


ANALYZER_SOURCE = _source_identity()


def _ratio(numerator, denominator, unit):
    """Keep the exact operands even when the convenience ratio is unavailable."""
    for value in (numerator, denominator):
        _require(value is None or type(value) is int and value >= 0,
                 "metric operands must be nonnegative integers or unavailable")
    reason = ("unavailable_operand" if numerator is None or denominator is None
              else "zero_denominator" if denominator == 0 else None)
    value = None if reason is not None else numerator / denominator
    _require(value is None or math.isfinite(value), "derived ratio is not finite")
    return {"unit": unit, "numerator": numerator, "denominator": denominator,
            "value": value, "unavailable_reason": reason}


def _quantity(value, unit):
    _require(value is None or type(value) is int and value >= 0,
             "metric quantity must be a nonnegative integer or unavailable")
    return {"unit": unit, "value": value,
            "unavailable_reason": "unavailable_counter" if value is None else None}


def _statistics(values):
    _require(values and all(type(value) in (int, float) and math.isfinite(value) for value in values),
             "statistics require finite measured values")
    return {"count": len(values), "minimum": min(values), "maximum": max(values),
            "median": statistics.median(values), "population_stddev": statistics.pstdev(values)}


def _sample_metrics(sample):
    observation = sample["observation"]
    accounting = observation["accounting"]
    counters = {row["name"]: row["value"] for row in observation["counter_deltas"]}
    block = observation["snapshots"]["begin"]["compiled_memory_block_bytes"]
    tensor_bytes = sum(accounting[name] for name in ("input_h2d_bytes", "poison_h2d_bytes", "tensor_d2h_bytes"))
    metrics = {
        "active_cycles_per_useful_flop": _ratio(counters["cycles"], accounting["flops"],
                                               METRICS["active_cycles_per_useful_flop"]["unit"]),
        "retired_macroinstructions_per_mac": _ratio(counters["instructions"], accounting["macs"],
                                                   METRICS["retired_macroinstructions_per_mac"]["unit"]),
        "logical_tensor_bytes": _quantity(tensor_bytes, "bytes"),
        "useful_flops_per_logical_tensor_byte": _ratio(accounting["flops"], tensor_bytes,
                                                     METRICS["useful_flops_per_logical_tensor_byte"]["unit"]),
    }
    for direction in ("read", "write"):
        requests = counters["memory_" + direction + "s"]
        value = None if requests is None else requests * block
        metrics["modeled_external_" + direction + "_request_bytes"] = {
            **_quantity(value, "modeled_request_bytes"),
            "requests": requests, "memory_block_bytes": block,
        }
    return {
        "sample_id": sample["sample_id"], "phase": sample["phase"], "repetition": sample["repetition"],
        "command_id": sample["command_id"], "raw_log_sha256": observation["raw_log_sha256"],
        "counter_values": counters, "metrics": metrics,
        "process_duration_seconds": sample["process_duration_seconds"],
        "host_timings_ns": deepcopy(observation["host_timings_ns"]),
    }


def _diagnostics(samples, workloads):
    result = []
    for workload in workloads:
        rows = [_sample_metrics(sample) for sample in samples if sample["workload_id"] == workload["id"]]
        measured = [row for row in rows if row["phase"] == "measurement"]
        metrics = {}
        for name, definition in METRICS.items():
            values = [row["metrics"][name]["value"] for row in measured]
            unavailable = [row["sample_id"] for row in measured if row["metrics"][name]["value"] is None]
            # Never silently reduce an incomplete subset of the five samples.
            metrics[name] = {
                **definition, "statistics": None if unavailable else _statistics(values),
                "unavailable_sample_ids": unavailable,
            }
        result.append({"workload_id": workload["id"], "format": workload["format"], "kind": workload["kind"],
                       "native_shapes": deepcopy(workload["native_shapes"]),
                       "accounting_per_invocation": deepcopy(workload["accounting"]),
                       "samples": rows, "measured_metric_statistics": metrics})
    return result


def _read_packet(path, sha256, replayed):
    api = replay._archive_api()
    with api.ArchiveReader(path, sha256) as archive:
        view = archive.view("baseline")
        _same(view.identity("report.json"), replayed["report_identity"], "replayed report identity")
        report = view.json("report.json")
        documents = {name: view.document(report[name + "_before"], "snapshots/" + name + "-before.json")
                     for name in ("source", "tools", "dependencies")}
        documents["contract"] = view.document(report["contract_snapshot"], "snapshots/contract.json")
        # Bind the exact manifest bytes, not merely an equivalent JSON object.
        documents["manifest"] = view.read("artifacts/source/ci/project/p06_benchmark_contract.json")
        identity = archive.receipt()["archive"]
    return {"report": report, "documents": documents, "archive": identity, "replay": replayed}


def _compatible(packets):
    first, second = packets
    common = {}
    for name in ("source", "dependencies", "contract", "manifest"):
        left, right = (packet["documents"][name] for packet in packets)
        _same(left, right, "cross-format " + name)
        common[name] = hashlib.sha256(left).hexdigest() if type(left) is bytes else _identity(left)
    # Recorded path prefixes describe each run's location; binary names, hashes
    # and sizes establish tool compatibility without erasing either provenance.
    tools = [{name: {key: row[key] for key in ("sha256", "size_bytes")}
              for name, row in packet["documents"]["tools"].items()} for packet in packets]
    _same(tools[0], tools[1], "cross-format tool identities")
    common["tools"] = _identity(tools[0])
    for name in ("contract_id", "contract_sha256", "sampling", "boundaries", "budget",
                 "loaded_helpers", "contract_limitations"):
        _same(first["report"][name], second["report"][name], "cross-format " + name)
    for name in ("header_macros", "expected_expanded_header_macros", "expected_backend_header_macros"):
        _same(first["report"]["variants"][0][name], second["report"]["variants"][0][name],
              "cross-format hardware " + name)
    jobs = [packet["replay"]["hosted_job_identity"] for packet in packets]
    _require((jobs[0] is None) == (jobs[1] is None), "cross-format hosted provenance is incomplete")
    if jobs[0] is not None:
        _same({key: value for key, value in jobs[0].items() if key != "P06_FORMAT"},
              {key: value for key, value in jobs[1].items() if key != "P06_FORMAT"},
              "cross-format hosted workflow/run identity")
    return {"outcome": "pass", "identity_sha256": common,
            "digest_encoding": "Manifest uses original bytes; other entries use sorted, compact canonical JSON.",
            "tool_comparison": "same names, SHA-256 and sizes; recorded paths checked separately",
            "format_bindings_compared_as_equal": False}


def analyze_archives(fp16_archive, fp16_sha256, bf16_archive, bf16_sha256, *, expected_revision):
    """Replay both originals, require one complete experiment, then derive data."""
    _same(_source_identity(), ANALYZER_SOURCE, "executing analyzer source stability")
    contract = load_contract(ROOT)
    packets = []
    try:
        for fmt, path, sha256 in (("fp16", fp16_archive, fp16_sha256), ("bf16", bf16_archive, bf16_sha256)):
            checked = replay.replay_archive(path, sha256, expected_revision=expected_revision, expected_format=fmt)
            packets.append(_read_packet(path, sha256, checked))
        compatibility = _compatible(packets)
        samples = [sample for packet in packets for sample in packet["report"]["samples"]]
        workloads = select_workloads(contract)
        summary = summarize(samples, contract, workloads)
        _same(summary["source_revision"], expected_revision, "full-matrix source")
        _same(summary["inventory"], contract["inventory"], "complete frozen matrix inventory")
        _same(summary["full_matrix"], True, "complete frozen format inventory")
        _same(summary["formats"], ["fp16", "bf16"], "canonical format order")
        inputs = []
        for packet in packets:
            checked, report = packet["replay"], packet["report"]
            inputs.append({"format": checked["format"], "archive": packet["archive"],
                           "binding_id": checked["binding_id"], "report_identity": checked["report_identity"],
                           "summary_identity": report["summary_snapshot"],
                           "commands_checked": checked["commands_checked"],
                           "retained_source_files_checked": checked["retained_source_files_checked"],
                           "hosted_job_identity": checked["hosted_job_identity"],
                           "inventory": checked["summary"]["inventory"]})
        _same(packets[0]["replay"]["trusted_replay_sources"], packets[1]["replay"]["trusted_replay_sources"],
              "trusted replay source stability across formats")
        _same(_source_identity(), ANALYZER_SOURCE, "analyzer source remained stable")
        return {"schema_version": 1, "scope": SCOPE, "outcome": "pass", "source_revision": expected_revision,
                "native_execution": "not_run", "acceptance_claimed": False, "phase_complete": False,
                "optimization_claimed": False, "inputs": inputs, "compatibility": compatibility,
                "summary": summary, "diagnostics": _diagnostics(samples, workloads),
                "metric_definitions": deepcopy(METRICS),
                "counter_null_policy": "Null means unavailable under the frozen configuration; see the original descriptor in summary.workloads[*].counter_statistics.",
                "trusted_analyzer_source": dict(ANALYZER_SOURCE),
                "trusted_replay_sources": packets[0]["replay"]["trusted_replay_sources"],
                "trusted_archive_reader": packets[0]["replay"]["trusted_archive_reader"],
                "limitations": list(LIMITATIONS)}
    except (KeyError, TypeError, IndexError, UnicodeError, OverflowError) as error:
        raise AnalysisError("malformed retained matrix: " + str(error)) from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for fmt in ("fp16", "bf16"):
        parser.add_argument("--" + fmt + "-archive", type=Path, required=True)
        parser.add_argument("--" + fmt + "-sha256", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = analyze_archives(args.fp16_archive, args.fp16_sha256, args.bf16_archive, args.bf16_sha256,
                                  expected_revision=args.source_revision)
        body = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output is None:
            print(body, end="")
        else:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(body)
            print(json.dumps({"outcome": "pass", "scope": SCOPE, "report": str(args.output),
                              "native_execution": "not_run", "acceptance_claimed": False}))
        return 0
    except (OSError, ValueError) as error:
        print(json.dumps({"outcome": "fail", "reason": str(error),
                          "native_execution": "not_run", "acceptance_claimed": False}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
