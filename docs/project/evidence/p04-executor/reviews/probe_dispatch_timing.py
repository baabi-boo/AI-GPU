#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Host-only timing regressions against retained P04 observations and mutated copies."""

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile


U64 = (1 << 64) - 1
HOST_FIELDS = ("bridge_ns", "bridge_compare_ns", "assembly_ns", "output_compare_ns")
STAGE_FIELDS = ("wait_ns", "compare_ns", "close_ns")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def nested_total(trace):
    terms = [trace[name] for name in HOST_FIELDS]
    for stage in trace["native"]:
        terms.extend(stage[name] for name in STAGE_FIELDS)
        terms.append(stage["submit_end_ns"] - stage["submit_begin_ns"])
    return min(U64, sum(terms))


def zero_durations(row):
    trace = row["trace"]
    for name in ("create_begin_ns", "create_end_ns", "advance_ns", "close_ns", *HOST_FIELDS):
        trace[name] = 0
    for stage in trace["native"]:
        for name in ("submit_begin_ns", "submit_end_ns", *STAGE_FIELDS):
            stage[name] = 0
        for profile in stage["dispatch"]["event_profiles"]:
            profile.update({name: 0 for name in profile})


def equal_queues(row):
    for stage in row["trace"]["native"]:
        for profile in stage["dispatch"]["event_profiles"]:
            profile["queued_ns"] = stage["submit_begin_ns"]


def reverse_queued(row, stage_index=0, pair=0):
    stage = row["trace"]["native"][stage_index]
    profiles = stage["dispatch"]["event_profiles"]
    begin = stage["submit_begin_ns"]
    assert begin < min(stage["submit_end_ns"], profiles[pair]["submit_ns"])
    for profile in profiles:
        profile["queued_ns"] = begin
    profiles[pair]["queued_ns"] = begin + 1


def excessive_waits(row):
    for stage in row["trace"]["native"]:
        stage["wait_ns"] = row["trace"]["advance_ns"] // 2


def advance_zero(row):
    row["trace"]["advance_ns"] = 0


def saturated(row, advance):
    row["trace"]["advance_ns"] = advance
    row["trace"]["native"][0]["wait_ns"] = U64


def single_duration(row, field, index=None):
    zero_durations(row)
    trace = row["trace"]
    if index is None:
        trace[field] = 1
    elif field != "submit":
        trace["native"][index][field] = 1
    else:
        trace["native"][index]["submit_end_ns"] = 1
        for stage in trace["native"][index + 1:]:
            stage.update(submit_begin_ns=1, submit_end_ns=1)
            for profile in stage["dispatch"]["event_profiles"]:
                profile.update({name: 1 for name in profile})


def outside_advance(row):
    zero_durations(row)
    row["trace"].update(create_end_ns=U64, close_ns=U64)
    for stage in row["trace"]["native"]:
        stage.update(submit_begin_ns=U64, submit_end_ns=U64)
        for profile in stage["dispatch"]["event_profiles"]:
            profile.update({name: U64 for name in profile})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", action="append", type=Path, required=True)
    parser.add_argument("--audit", type=Path, default=Path(__file__).with_name("audit_dispatch.py"))
    parser.add_argument("--selected-scope", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("audit_under_test", args.audit)
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    packets = [path.resolve() if path.name != "report.json" else path.resolve().parent for path in args.packet]
    actual = audit.audit_packets(packets, allow_partial=args.selected_scope)
    reports = [json.loads((packet / "report.json").read_bytes()) for packet in packets]
    observations = [row for report in reports for variant in report["variants"]
                    for case in variant["cases"] for row in case["observations"]]
    slack = [row["trace"]["advance_ns"] - nested_total(row["trace"]) for row in observations]
    assert observations and min(slack) >= 0
    report = reports[0]
    variant = report["variants"][0]
    case = variant["cases"][0]
    base = case["observations"][0]
    probes = []

    def run_record(name, mutate, expected, expected_reason=None):
        row = copy.deepcopy(base)
        mutate(row)
        try:
            audit.audit_record(row, case_id=case["id"], backend=variant["backend"],
                               fmt=variant["format"], revision=row["source_revision"],
                               binding=variant["qualification_id"], iteration=0, statistics={})
            outcome, reason = "accepted", None
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            outcome, reason = "rejected", str(error)
        assert outcome == expected, (name, outcome, reason)
        assert expected_reason is None or reason == expected_reason, (name, reason)
        probes.append(dict(probe=name, layer="record", expected=expected, outcome=outcome, reason=reason))

    duration_reason = "disjoint nested host durations exceed advance"
    queue_reason = "sequential enqueue timestamps reversed"
    run_record("all_zero_durations_and_timestamps", zero_durations, "accepted")
    run_record("equal_sequential_enqueue_timestamps", equal_queues, "accepted")
    run_record("nested_sum_equals_advance", lambda row: row["trace"].update(
        advance_ns=nested_total(row["trace"])), "accepted")
    run_record("nested_sum_exceeds_advance_by_one", lambda row: row["trace"].update(
        advance_ns=nested_total(row["trace"]) - 1), "rejected", duration_reason)
    run_record("advance_zero_positive_nested_duration", advance_zero, "rejected", duration_reason)
    run_record("disjoint_wait_sum_exceeds_advance", excessive_waits, "rejected", duration_reason)
    run_record("saturated_nested_sum_equals_advance", lambda row: saturated(row, U64), "accepted")
    run_record("saturated_nested_sum_exceeds_advance", lambda row: saturated(row, U64 - 1),
               "rejected", duration_reason)
    run_record("create_and_model_close_excluded", outside_advance, "accepted")
    for index in range(3):
        for pair in range(4):
            run_record(f"stage_{index}_reverse_enqueue_pair_{pair}",
                       lambda row, i=index, p=pair: reverse_queued(row, i, p), "rejected", queue_reason)
        for field in ("submit", *STAGE_FIELDS):
            run_record(f"stage_{index}_{field}_inside_advance",
                       lambda row, f=field, i=index: single_duration(row, f, i), "rejected", duration_reason)
    for field in HOST_FIELDS:
        run_record(field + "_inside_advance", lambda row, f=field: single_duration(row, f),
                   "rejected", duration_reason)

    def run_packet(name, mutate, expected_reason):
        with tempfile.TemporaryDirectory(prefix="p04-dispatch-timing-") as temp:
            target = Path(temp) / "model"
            shutil.copytree(packets[0], target)
            modified = copy.deepcopy(report)
            changed = modified["variants"][0]["cases"][0]
            mutate(changed["observations"][0])
            command = next(command for command in modified["commands"]
                           if command["id"] == variant["id"] + "-" + changed["id"])
            log_path = target / command["log"]
            lines = log_path.read_text().splitlines()
            record_index = 0
            for index, line in enumerate(lines):
                if line.startswith("P04_RESULT "):
                    lines[index] = "P04_RESULT " + json.dumps(changed["observations"][record_index], separators=(",", ":"))
                    record_index += 1
            assert record_index == 2
            log = ("\n".join(lines) + "\n").encode()
            log_path.write_bytes(log)
            command.update(log_sha256=hashlib.sha256(log).hexdigest(), log_size_bytes=len(log))
            (target / "report.json").write_text(json.dumps(modified, indent=2, sort_keys=True) + "\n")
            try:
                audit.audit_packets([target], allow_partial=True)
                outcome, reason = "accepted", None
            except (ValueError, KeyError, TypeError, OverflowError) as error:
                outcome, reason = "rejected", str(error)
            assert outcome == "rejected" and reason == expected_reason, (name, outcome, reason)
            probes.append(dict(probe=name, layer="packet_with_rehashed_matching_raw_log", expected="rejected",
                               outcome=outcome, reason=reason, mutated_report_sha256=digest(target / "report.json"),
                               mutated_log_sha256=digest(log_path)))

    run_packet("advance_zero_positive_nested_duration", advance_zero, duration_reason)
    run_packet("disjoint_wait_sum_exceeds_advance", excessive_waits, duration_reason)
    run_packet("reverse_sequential_enqueue_timestamps", reverse_queued, queue_reason)
    result = dict(schema_version=1, outcome="pass", phase_acceptance=False,
                  scope="Host-only auditor regressions; mutated copies are not native execution evidence.",
                  audit_sha256=digest(args.audit), probe_sha256=digest(Path(__file__)),
                  source_revision=actual["source_revision"], source_tree=actual["source_tree"],
                  actual_matrix_counts=actual["counts"], full_matrix_checked=actual["full_matrix_checked"],
                  actual_reports=actual["reports"], actual_record_count=len(observations),
                  actual_minimum_nested_slack_ns=min(slack),
                  actual_audit_result_sha256=hashlib.sha256((json.dumps(actual, indent=2, sort_keys=True,
                      allow_nan=False) + "\n").encode()).hexdigest(),
                  probe_count=len(probes), probes=probes,
                  limitations=["No simulator was executed and no phase was accepted.",
                               "These checks do not establish compiler/source provenance or repair omitted retained artifacts.",
                               "Create/owner-close and overlapping event profiles are excluded from nested host accounting."])
    encoded = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    print(encoded, end="")


if __name__ == "__main__":
    main()
