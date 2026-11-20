#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Independently audit retained P04 dispatch observations; never execute a model.

Only Python's standard library is used. Numerical recomputation, compiler-role
validation and authentication of the originating runner are separate reviews.
Pass four packet directories with --packet, or explicitly use --allow-partial.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
import sys


MAX_BYTES = 16 * 1024 * 1024
MAX_RECORD = 256 * 1024
U64 = (1 << 64) - 1
FIXTURE_SHA = "d22a899827afb3e8c22a528fc6a27fd12ff114ef39caf9ffa0cccd77e849cd03"
PROFILE_SHA = "79a551bd7ba51b5aa4b221eeb9c8f68b0f3078e6282ce71a1f28e9bc4593a102"
FAMILIES = ("seeded_dense", "negated_dense", "zero", "signed_basis", "split_boundary")
VARIANTS = {(backend, fmt) for backend in ("simx", "rtlsim") for fmt in ("fp16", "bf16")}
GRAPH = (("hidden_matmul", (16, 8, 16), (0, 16)),
         ("output_rows_0_7", (8, 4, 8), (0, 8)),
         ("output_rows_8_15", (8, 4, 8), (8, 16)))
TOP_FIELDS = {"schema_version", "model_id", "fixture_id", "fixture_sha256", "source_revision",
              "backend", "iteration", "qualification_id", "clock", "timing_scope", "trace"}
TRACE_FIELDS = set(("case_id input_dtype poison native hidden_valid bridge_attempted bridge_valid "
    "bridge_compared assembled logits_valid logits_compared owner_closed bridge_status hidden_words "
    "bridge_bytes bridge_words output_words bridge_checked_words bridge_mismatches output_checked_words "
    "output_mismatches create_begin_ns create_end_ns advance_ns bridge_ns bridge_compare_ns assembly_ns "
    "output_compare_ns close_ns resources owner_cleanup result").split())
STAGE_FIELDS = set(("operation_id sequence row_begin row_end submitted waited trace_valid output_valid "
    "compared closed submission completion cleanup dispatch a_size b_size output_count a_bytes b_bytes "
    "output_words checked_words mismatches submit_begin_ns submit_end_ns wait_ns compare_ns close_ns").split())
DISPATCH_FIELDS = set(("qualification_id input_dtype m n k poison a_address b_address d_address "
    "a_bytes b_bytes d_bytes argument_bytes writes_enqueued launches_enqueued reads_enqueued wait_calls "
    "timed_out_waits event_results profiling_enabled event_profiles event_profile_results event_profile_queried").split())


def check(condition, message):
    if not condition:
        raise ValueError(message)


def uint(value, label):
    check(type(value) is int and 0 <= value <= U64, label + " must be an unsigned integer")
    return value


def exact_number(value, wanted, label):
    check(uint(value, label) == wanted, label + " differs")


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        check(key not in value, "duplicate JSON key: " + key)
        value[key] = item
    return value


def invalid_number(token):
    raise ValueError("noninteger or nonfinite record number: " + token[:40])


def parse_json(data, *, record=False):
    check(len(data) <= (MAX_RECORD if record else MAX_BYTES), "JSON exceeds byte bound")
    options = {"object_pairs_hook": unique_object, "parse_constant": invalid_number}
    if record:
        options["parse_float"] = invalid_number
    return json.loads(data.decode("utf-8"), **options)


def packet_file(root, relative):
    check(type(relative) is str, "packet path must be text")
    name = PurePosixPath(relative)
    check(not name.is_absolute() and name.parts and ".." not in name.parts
          and name.as_posix() == relative, "unsafe packet-relative path")
    path = root / relative
    check(path.resolve(strict=True) == path and path.is_file(), "packet input is not a regular plain file")
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    check(len(data) <= MAX_BYTES, "packet input exceeds byte bound")
    return data


def verified_file(root, descriptor):
    check(type(descriptor) is dict and {"path", "sha256", "size_bytes"} <= descriptor.keys(),
          "incomplete artifact descriptor")
    data = packet_file(root, descriptor["path"])
    check(hashlib.sha256(data).hexdigest() == descriptor["sha256"], "artifact digest differs: " + descriptor["path"])
    exact_number(descriptor["size_bytes"], len(data), "artifact size")
    return data


def successful_result(result, label, *, pending_submission=False):
    check(type(result) is dict and set(result) == {"validation", "primary", "cleanup", "complete"},
          label + " has incorrect result fields")
    for name in ("validation", "primary", "cleanup"):
        exact_number(result[name], 0, label + "." + name)
    check(type(result["complete"]) is bool, label + " completion is not boolean")
    check(pending_submission or result["complete"], label + " is incomplete")


def hex_bytes(value, size, label):
    check(type(value) is str and re.fullmatch(r"[0-9a-f]{" + str(size * 2) + "}", value),
          label + " has incorrect byte encoding")
    return bytes.fromhex(value)


def word_array(value, count, label):
    check(type(value) is list and len(value) == count and all(
        type(word) is str and re.fullmatch(r"[0-9a-f]{8}", word) for word in value),
        label + " has incorrect word encoding")
    return value


def add_sample(statistics, name, value):
    summary = statistics.setdefault(name, {"samples": 0, "sum_ns": 0, "min_ns": value, "max_ns": value})
    summary["samples"] += 1
    summary["sum_ns"] += value
    summary["min_ns"] = min(summary["min_ns"], value)
    summary["max_ns"] = max(summary["max_ns"], value)


def audit_record(row, *, case_id, backend, fmt, revision, binding, iteration, statistics):
    check(type(row) is dict and set(row) == TOP_FIELDS, "incorrect top-level record fields")
    exact_number(row["schema_version"], 1, "record schema")
    exact_number(row["iteration"], iteration, "iteration")
    for key, expected in (("model_id", "p04-tiny-mlp-v1"), ("fixture_id", "p04-tiny-mlp-fixture-v1"),
                          ("fixture_sha256", FIXTURE_SHA), ("source_revision", revision),
                          ("backend", backend), ("qualification_id", binding),
                          ("clock", "std::chrono::steady_clock"), ("timing_scope", "host_runtime_observations")):
        check(row[key] == expected, "record identity differs: " + key)
    trace = row["trace"]
    check(type(trace) is dict and set(trace) == TRACE_FIELDS, "model trace fields differ")
    check(trace["case_id"] == case_id and trace["input_dtype"] == fmt, "model case or dtype differs")
    poison = (0x7FC0DEAD, 0xDEADBEEF)[iteration]
    exact_number(trace["poison"], poison, "model poison")
    for flag in ("hidden_valid", "bridge_attempted", "bridge_valid", "bridge_compared", "assembled",
                 "logits_valid", "logits_compared", "owner_closed"):
        check(trace[flag] is True, "missing successful model observation: " + flag)
    exact_number(trace["bridge_status"], 0, "bridge status")
    successful_result(trace["owner_cleanup"], "owner cleanup")
    check(set(trace["result"]) == {"status", "execution", "terminal"}
          and trace["result"]["status"] == "success" and trace["result"]["terminal"] is True,
          "model is not terminal and successful")
    successful_result(trace["result"]["execution"], "model completion")
    memory = trace["resources"]
    check(set(memory) == {"before_valid", "after_valid", "before_status", "after_status",
                         "free_before", "used_before", "free_after", "used_after"}, "incorrect memory observation fields")
    for when in ("before", "after"):
        check(memory[when + "_valid"] is True, "memory query was not observed")
        exact_number(memory[when + "_status"], 0, "memory query status")
    for quantity in ("free", "used"):
        before = uint(memory[quantity + "_before"], "memory " + quantity)
        check(before == uint(memory[quantity + "_after"], "memory " + quantity), "memory baseline was not restored")
    begin = uint(trace["create_begin_ns"], "create begin")
    previous_end = uint(trace["create_end_ns"], "create end")
    check(begin <= previous_end, "creation timestamps reversed")
    add_sample(statistics, "host.create", previous_end - begin)
    for name in ("advance_ns", "bridge_ns", "bridge_compare_ns", "assembly_ns", "output_compare_ns", "close_ns"):
        add_sample(statistics, "host." + name.removesuffix("_ns"), uint(trace[name], name))
    for count, expected in (("bridge_checked_words", 64), ("bridge_mismatches", 0),
                            ("output_checked_words", 64), ("output_mismatches", 0)):
        exact_number(trace[count], expected, count)
    bridge = hex_bytes(trace["bridge_bytes"], 256, "bridge")
    hidden = word_array(trace["hidden_words"], 128, "hidden")
    final = word_array(trace["output_words"], 64, "final output")
    bridge_words = word_array(trace["bridge_words"], 64, "bridge words")
    check(bridge == b"".join(int(word, 16).to_bytes(4, "little") for word in bridge_words), "bridge representations disagree")
    stages = trace["native"]
    check(type(stages) is list and len(stages) == 3, "native graph must contain three stages")
    nested_host_ns = sum(trace[name] for name in (
        "bridge_ns", "bridge_compare_ns", "assembly_ns", "output_compare_ns"))
    h2d = d2h = 0
    blocks = []
    for index, (stage, (operation, shape, rows)) in enumerate(zip(stages, GRAPH)):
        check(type(stage) is dict and set(stage) == STAGE_FIELDS, "native stage fields differ")
        m, n, k = shape
        check(stage["operation_id"] == operation, "native stage order differs")
        for key, wanted in (("sequence", index), ("row_begin", rows[0]), ("row_end", rows[1]),
                             ("a_size", m * k * 2), ("b_size", k * n * 2),
                             ("output_count", m * n), ("checked_words", m * n), ("mismatches", 0)):
            exact_number(stage[key], wanted, "stage " + key)
        for flag in ("submitted", "waited", "trace_valid", "output_valid", "compared", "closed"):
            check(stage[flag] is True, "missing successful stage observation: " + flag)
        successful_result(stage["submission"], "submission", pending_submission=True)
        successful_result(stage["completion"], "completion")
        successful_result(stage["cleanup"], "operation cleanup")
        submitted_begin = uint(stage["submit_begin_ns"], "stage submit begin")
        submitted_end = uint(stage["submit_end_ns"], "stage submit end")
        check(previous_end <= submitted_begin <= submitted_end, "stage precedes its dependency")
        add_sample(statistics, "host.submit", submitted_end - submitted_begin)
        nested_host_ns += submitted_end - submitted_begin
        for name in ("wait_ns", "compare_ns", "close_ns"):
            duration = uint(stage[name], name)
            add_sample(statistics, "stage." + name.removesuffix("_ns"), duration)
            nested_host_ns += duration
        a = hex_bytes(stage["a_bytes"], m * k * 2, "stage A")
        hex_bytes(stage["b_bytes"], k * n * 2, "stage B")
        words = word_array(stage["output_words"], m * n, "stage output")
        if index == 0:
            check(words == hidden, "actual hidden record differs from native output")
        else:
            check(a == bridge[(index - 1) * 128:index * 128], "output call does not consume its actual bridge slice")
            blocks.extend(words)
        dispatch = stage["dispatch"]
        check(type(dispatch) is dict and set(dispatch) == DISPATCH_FIELDS, "dispatch fields differ")
        check(dispatch["qualification_id"] == binding and dispatch["input_dtype"] == fmt, "dispatch binding or dtype differs")
        for key, wanted in zip(("m", "n", "k"), shape):
            exact_number(dispatch[key], wanted, "dispatch " + key)
        for key, wanted in (("poison", poison), ("a_bytes", m * k * 2), ("b_bytes", k * n * 2),
                            ("d_bytes", m * n * 4), ("writes_enqueued", 3),
                            ("launches_enqueued", 1), ("reads_enqueued", 1)):
            exact_number(dispatch[key], wanted, key)
        check(uint(dispatch["wait_calls"], "wait calls") > uint(dispatch["timed_out_waits"], "timeout waits"),
              "no completed non-timeout wait observed")
        addresses = [uint(dispatch[name + "_address"], name + " address") for name in ("a", "b", "d")]
        sizes = (m * k * 2, k * n * 2, m * n * 4)
        intervals = []
        for address, size in zip(addresses, sizes):
            check(address % 4 == 0 and address + size <= 1 << 64, "misaligned or overflowing allocation")
            intervals.append((address, address + size))
        ordered = sorted(intervals)
        check(all(left[1] <= right[0] for left, right in zip(ordered, ordered[1:])), "operand allocations overlap")
        arguments = struct.pack("<8I3Q", 1, 56, {"fp16": 1, "bf16": 2}[fmt], 0, m, n, k, 0, *addresses)
        check(hex_bytes(dispatch["argument_bytes"], 56, "launch argument block") == arguments, "launch ABI differs")
        check(dispatch["profiling_enabled"] is True, "profiling was not enabled")
        for field in ("event_results", "event_profile_results", "event_profile_queried", "event_profiles"):
            check(type(dispatch[field]) is list and len(dispatch[field]) == 5, "five-event inventory differs")
        prior_event_end = previous_end
        prior_queued = submitted_begin
        for event, profile in enumerate(dispatch["event_profiles"]):
            exact_number(dispatch["event_results"][event], 0, "event result")
            exact_number(dispatch["event_profile_results"][event], 0, "profile query result")
            check(dispatch["event_profile_queried"][event] is True, "profile was not queried")
            check(set(profile) == {"queued_ns", "submit_ns", "start_ns", "end_ns"}, "profile fields differ")
            queued, submit, start, end = [uint(profile[key], key) for key in
                                          ("queued_ns", "submit_ns", "start_ns", "end_ns")]
            check(submitted_begin <= queued <= submitted_end, "event was queued outside submission")
            check(prior_queued <= queued, "sequential enqueue timestamps reversed")
            check(queued <= submit <= start <= end and prior_event_end <= submit, "event dependency chronology differs")
            prior_queued = queued
            prior_event_end = end
            kind = "h2d" if event < 3 else "launch" if event == 3 else "d2h"
            for phase, duration in (("queue", submit - queued), ("preparation", start - submit), ("service", end - start)):
                add_sample(statistics, "event." + kind + "." + phase, duration)
        previous_end = prior_event_end
        h2d += sum(sizes)
        d2h += sizes[2]
    check(final == blocks, "row-block assembly differs from actual native outputs")
    # Only disjoint work inside successful advance calls contributes; counters saturate at uint64.
    check(min(U64, nested_host_ns) <= trace["advance_ns"], "disjoint nested host durations exceed advance")
    return {"create_begin_ns": begin, "last_read_end_ns": previous_end, "launches": 3,
            "events": 15, "tensor_h2d_bytes": h2d, "tensor_d2h_bytes": d2h,
            "host_assembly_bytes": len(final) * 4}


def raw_observations(data):
    text = data.decode("utf-8")
    check(not any(ord(char) < 32 and char not in "\n\r\t" or 127 <= ord(char) < 160 for char in text),
          "control character in native log")
    lines = text.splitlines()
    check(sum(line == "PASSED!" for line in lines) == 1 and lines[-1] == "PASSED!", "native success framing differs")
    check(not re.search(r"\b(?:FAILED|FAILURE|ERROR|P04_FAILURE|P04_DRAIN)\b", text, re.IGNORECASE), "failure text in native log")
    observations = []
    for line in lines[:-1]:
        if line.startswith("P04_RESULT "):
            observations.append(parse_json(line[len("P04_RESULT "):].encode(), record=True))
        else:
            check(not re.search(r"P04_RESULT|PASSED", line, re.IGNORECASE), "ambiguous native result marker")
    check(len(observations) == 2, "expected two poison repetitions")
    return observations


def audit_packets(inputs, allow_partial=False):
    seen, source_identity, dependency_identity = set(), None, None
    reports, variants = [], []
    totals = {name: 0 for name in ("case_executions", "model_runs", "launches", "events",
                                    "tensor_h2d_bytes", "tensor_d2h_bytes", "host_assembly_bytes")}
    for supplied in inputs:
        root = Path(supplied).absolute()
        if root.name == "report.json":
            root = root.parent
        check(root.resolve(strict=True) == root and root.is_dir(), "packet root must be a plain existing directory")
        encoded = packet_file(root, "report.json")
        report = parse_json(encoded)
        exact_number(report["schema_version"], 1, "packet schema")
        check(report["contract_id"] == "p04-managed-model-execution-v1" and report["state"] == "finished"
              and report["outcome"] == "pass" and report["reason"] is None, "packet is not a finished passing run")
        check(report["development"] is False and report["source_stable"] is True, "development or unstable packet")
        check(report["acceptance_claimed"] is False and report["phase_complete"] is False, "runner packet claims acceptance")
        exact_number(report["iterations"], 2, "packet repetitions")
        check(report["fixture_sha256"] == FIXTURE_SHA, "packet fixture differs from frozen fixture")
        budget = report["budget"]
        exact_number(budget["max_log_bytes"], MAX_BYTES, "command log cap")
        check(0 < uint(budget["max_rss_bytes"], "RSS budget") <= 4 * 1024**3
              and uint(budget["min_free_bytes"], "disk reserve") >= 15 * 1024**3
              and 1 <= uint(budget["jobs"], "build jobs") <= 2, "packet exceeds frozen resource budget")
        before = parse_json(verified_file(root, report["source_before"]))
        after = parse_json(verified_file(root, report["source_after"]))
        check(before == after, "recorded source inventories differ")
        checkout = before["checkout"]
        check(checkout["dirty"] is False and not checkout["blockers"] and not checkout["changed_paths"]
              and not checkout["untracked_paths"], "source is not clean")
        identity = (checkout["revision"], checkout["tree"])
        check(all(type(value) is str and re.fullmatch("[0-9a-f]{40}", value) for value in identity), "invalid source identity")
        if source_identity is None:
            source_identity = identity
            dependency_identity = report["dependencies_before"]
        check(identity == source_identity and report["dependencies_before"] == dependency_identity,
              "mixed source trees or dependency binaries across packets")
        check(parse_json(verified_file(root, report["tools_before"])) ==
              parse_json(verified_file(root, report["tools_after"])), "recorded tool inventories differ")
        commands = {}
        for command in report["commands"]:
            check(command["id"] not in commands, "duplicate command ID")
            check(command["outcome"] == "pass" and command["process_started"] is True
                  and command["cleanup_complete"] is True, "incomplete or failed command")
            exact_number(command["exit_code"], 0, "command exit")
            check(0 < uint(command["timeout_seconds"], "command deadline") <= 1800
                  and uint(command["peak_rss_bytes"], "observed peak RSS") <= budget["max_rss_bytes"],
                  "passing command exceeds its resource/deadline bound")
            log = packet_file(root, command["log"])
            exact_number(command["log_size_bytes"], len(log), "command log size")
            check(hashlib.sha256(log).hexdigest() == command["log_sha256"], "command log digest differs")
            commands[command["id"]] = (command, log)
        packet_counts = {name: 0 for name in totals}
        used_native_commands = set()
        check(type(report["variants"]) is list and report["full_matrix_requested"] is (len(report["variants"]) == 4),
              "packet full-matrix claim differs from its variant inventory")
        for variant in report["variants"]:
            key = (variant["backend"], variant["format"])
            check(key in VARIANTS and key not in seen, "unknown or duplicate backend/format variant")
            seen.add(key)
            backend, fmt = key
            identifier = backend + "-" + fmt
            check(variant["id"] == identifier and variant["outcome"] == "pass", "variant is not passing")
            binding = parse_json(verified_file(root, variant["binding"]))
            binding_id = hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
            check(binding_id == variant["qualification_id"], "canonical qualification binding digest differs")
            check(binding["source"] == checkout and (binding["backend"], binding["format"]) == key
                  and binding["profile_sha256"] == PROFILE_SHA and binding["fixture_sha256"] == FIXTURE_SHA
                  and binding["model_id"] == "p04-tiny-mlp-v1", "binding source/profile/fixture differs")
            check(binding["artifacts"] == variant["artifacts_before"] == variant["artifacts_after"]
                  and binding["dependencies"] == report["dependencies_before"]
                  and binding["compiler_records"] == variant["compiler_records"], "binding inventories differ")
            case_ids = [fmt + "-" + family for family in FAMILIES]
            check([case["id"] for case in variant["cases"]] == case_ids, "five-case inventory or order differs")
            statistics = {}
            for case in variant["cases"]:
                check(case["outcome"] == "pass", "case did not pass")
                command_id = identifier + "-" + case["id"]
                command, log = commands[command_id]
                used_native_commands.add(command_id)
                check(0 < command["timeout_seconds"] <= 180, "case exceeds frozen invocation deadline")
                arguments = command["argv"]
                check(len(arguments) == 13 and arguments[1::2] == ["--case", "--iterations", "--module",
                      "--qualification-id", "--backend", "--source-revision"], "native command argument structure differs")
                check(arguments[2] == case["id"] and arguments[4] == "2" and arguments[8] == binding_id
                      and arguments[10] == backend and arguments[12] == checkout["revision"]
                      and command["environment"]["VORTEX_DRIVER"] == backend, "native invocation binding differs")
                rows = raw_observations(log)
                check(rows == case["observations"], "raw records differ from reported observations")
                previous_end = 0
                for iteration, row in enumerate(rows):
                    observed = audit_record(row, case_id=case["id"], backend=backend, fmt=fmt,
                        revision=checkout["revision"], binding=binding_id, iteration=iteration, statistics=statistics)
                    check(previous_end <= observed["create_begin_ns"], "poison repetitions overlap or reorder")
                    previous_end = observed["last_read_end_ns"]
                    for name in ("launches", "events", "tensor_h2d_bytes", "tensor_d2h_bytes", "host_assembly_bytes"):
                        packet_counts[name] += observed[name]
                    packet_counts["model_runs"] += 1
                packet_counts["case_executions"] += 1
            variants.append({"id": identifier, "qualification_id": binding_id, "cases": case_ids,
                             "timings_ns": statistics})
        check(used_native_commands == {name for name, (command, _) in commands.items() if "--case" in command["argv"]},
              "native invocations and reported case inventory differ")
        for reported, counted in (("completed_case_executions", "case_executions"),
                                  ("completed_model_runs", "model_runs"), ("completed_launches", "launches"),
                                  ("tensor_h2d_bytes", "tensor_h2d_bytes"), ("tensor_d2h_bytes", "tensor_d2h_bytes")):
            exact_number(report[reported], packet_counts[counted], "reported " + reported)
        for name, value in packet_counts.items():
            totals[name] += value
        reports.append({"packet": str(root), "report_sha256": hashlib.sha256(encoded).hexdigest(), "counts": packet_counts})
    check(seen and (allow_partial or seen == VARIANTS), "full four-variant matrix is incomplete")
    return {"schema_version": 1, "audit": "p04-independent-dispatch-v1", "outcome": "pass",
            "phase_acceptance": False, "full_matrix_checked": seen == VARIANTS,
            "source_revision": source_identity[0], "source_tree": source_identity[1],
            "fixture_sha256": FIXTURE_SHA, "profile_sha256": PROFILE_SHA,
            "counts": totals, "reports": reports, "variants": sorted(variants, key=lambda row: row["id"]),
            "limitations": [
                "This audit reads retained observations; it does not execute or authenticate the originating runner.",
                "Independent numerical recomputation and native compiler-role/source review are separate obligations.",
                "Memory snapshots bracket tensor operations while the owner/module exists; owner cleanup is checked separately.",
                "Host durations overlap event profiles and advance contains nested work; reported categories must not be summed as disjoint cost.",
                "Per-variant timestamp durations may be summarized; absolute host steady clocks from separate jobs are not aligned.",
                "Queue service includes runtime synchronization/staging; it is not physical device latency, throughput or speedup.",
                "Tensor bytes include destination poison and exclude argument/control/module/setup traffic; physical transactions are not measured.",
            ]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", action="append", type=Path, required=True)
    parser.add_argument("--allow-partial", "--selected-scope", action="store_true", dest="allow_partial")
    parser.add_argument("--output", type=Path, help="write a fresh JSON receipt; existing files are not replaced")
    arguments = parser.parse_args(argv)
    try:
        result = audit_packets(arguments.packet, arguments.allow_partial)
    except (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError) as error:
        result = {"schema_version": 1, "audit": "p04-independent-dispatch-v1", "outcome": "fail",
                  "phase_acceptance": False, "reason": str(error)}
    encoded = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if arguments.output:
        with arguments.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    print(encoded, end="")
    return 0 if result["outcome"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
