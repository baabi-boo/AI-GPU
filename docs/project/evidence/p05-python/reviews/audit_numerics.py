#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Audit retained P05 numerical observations without executing a backend."""

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import sys


LIMIT = 16 * 1024 * 1024
RECORD_LIMIT = 256 * 1024
TOTAL_LIMIT = 128 * 1024 * 1024
FORMATS = ("fp16", "bf16")
FAMILIES = ("seeded_dense", "negated_dense", "zero", "signed_basis", "split_boundary")
SELECTION = (("single-dense_boundaries", (8, 4, 8)),
             ("numerical-cross_tile_rounding_positive", (8, 4, 16)),
             ("multi-dense_boundaries", (16, 8, 16)))
POISONS = (0x7FC0DEAD, 0xDEADBEEF)
FIXTURES = {
    "p02_layout_v1.json": "0543f9f4208de3ff4743fe1894d97ccf3b8cca4707e9a26acd1f3dde884725b2",
    "p02_wmma_numerical_v1.json": "4102d74024e92e9887d7324b9326c0d6ad1fff206b5fad33f45c530d5bd03a73",
    "p04_tiny_mlp_v1.json": "d22a899827afb3e8c22a528fc6a27fd12ff114ef39caf9ffa0cccd77e849cd03",
}
HELPER = "docs/project/evidence/p04-executor/reviews/audit_numerics.py"
HELPER_SHA256 = "d7130898b8d3d0690c7cf03459d50e2301ab9fcbcd928562c599bdaea32d918e"
HEX = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
WORD = re.compile(r"[0-9a-f]{8}\Z")
READS = {}
STATUS = {"validation", "primary", "cleanup", "complete"}
BINDING = {"backend", "format", "bundle_root", "bundle_sha256", "source_sha256",
           "qualification_id", "source_revision"}
RESULT = {"schema_version", "model_id", "fixture_id", "fixture_sha256", "source_revision",
          "backend", "iteration", "qualification_id", "clock", "timing_scope", "trace"}
TRACE_FLAGS = {"hidden_valid", "bridge_attempted", "bridge_valid", "bridge_compared", "assembled",
               "logits_valid", "logits_compared", "owner_closed"}
TRACE_TIMES = {"create_begin_ns", "create_end_ns", "advance_ns", "bridge_ns", "bridge_compare_ns",
               "assembly_ns", "output_compare_ns", "close_ns"}
TRACE = {"case_id", "input_dtype", "poison", "native", "bridge_status", "hidden_words",
         "bridge_bytes", "bridge_words", "output_words", "bridge_checked_words",
         "bridge_mismatches", "output_checked_words", "output_mismatches", "resources",
         "owner_cleanup", "result"} | TRACE_FLAGS | TRACE_TIMES
STAGE_FLAGS = {"submitted", "waited", "trace_valid", "output_valid", "compared", "closed"}
STAGE_TIMES = {"submit_begin_ns", "submit_end_ns", "wait_ns", "compare_ns", "close_ns"}
STAGE = {"operation_id", "sequence", "row_begin", "row_end", "submission", "completion",
         "cleanup", "dispatch", "a_size", "b_size", "output_count", "a_bytes", "b_bytes",
         "output_words", "checked_words", "mismatches"} | STAGE_FLAGS | STAGE_TIMES
DISPATCH_NUMBERS = {"m", "n", "k", "poison", "a_address", "b_address", "d_address", "a_bytes",
                    "b_bytes", "d_bytes", "writes_enqueued", "launches_enqueued", "reads_enqueued",
                    "wait_calls", "timed_out_waits"}
DISPATCH = DISPATCH_NUMBERS | {"qualification_id", "input_dtype", "argument_bytes", "event_results",
                             "profiling_enabled", "event_profiles", "event_profile_results",
                             "event_profile_queried"}


def need(condition, message):
    if not condition:
        raise ValueError(message)


def same(actual, expected, label):
    need(canonical(actual) == canonical(expected), label + " differs")


def fields(value, keys, label):
    need(type(value) is dict and set(value) == keys, label + " fields differ")


def uint(value, label, expected=None):
    need(type(value) is int and 0 <= value < 1 << 64, label + " is not a uint64")
    need(expected is None or value == expected, label + " differs")
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def number(token, integer=False):
    need(len(token) <= 64, "oversized JSON number")
    value = int(token) if integer else float(token)
    need(integer or math.isfinite(value), "nonfinite JSON number")
    return value


def reject_number(token):
    raise ValueError("noninteger/nonfinite observation number: " + token[:32])


def decode(data, observations=False):
    need(type(data) is bytes and len(data) <= LIMIT, "JSON input exceeds byte bound")
    value = json.loads(data.decode("utf-8"), object_pairs_hook=unique,
                       parse_int=lambda token: number(token, True),
                       parse_float=reject_number if observations else number,
                       parse_constant=reject_number)
    pending, count = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        count += 1
        need(depth <= 64 and count <= 300000, "JSON exceeds structure bound")
        if isinstance(item, (dict, list)):
            pending.extend((child, depth + 1) for child in (item.values() if isinstance(item, dict) else item))
    return value


def plain(path, directory=False):
    need(path.is_absolute() and path.resolve(strict=True) == path, "path is not canonical: " + str(path))
    mode = path.stat().st_mode
    need(stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode), "path has wrong file type: " + str(path))
    return path


def member(root, name):
    need(type(name) is str and name and len(name) <= 1024 and not any(ord(c) < 32 for c in name),
         "invalid retained member name")
    relative = PurePosixPath(name)
    need(not relative.is_absolute() and ".." not in relative.parts and str(relative) == name,
         "unsafe retained member name")
    return root.joinpath(*relative.parts)


def read_file(path, limit=LIMIT):
    plain(path)
    need(path.stat().st_size <= limit, "input exceeds byte bound: " + str(path))
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    need(len(data) <= limit, "input exceeds byte bound: " + str(path))
    receipt = {"path": str(path), "sha256": digest(data), "size_bytes": len(data)}
    previous = READS.get(str(path))
    need(previous is None or previous == receipt, "input changed during audit: " + str(path))
    READS[str(path)] = receipt
    need(sum(row["size_bytes"] for row in READS.values()) <= TOTAL_LIMIT, "aggregate read bound exceeded")
    return data


def identified(root, descriptor, expected):
    fields(descriptor, {"path", "sha256", "size_bytes"}, "retained descriptor")
    same(descriptor["path"], expected, "retained path")
    data = read_file(member(root, descriptor["path"]))
    uint(descriptor["size_bytes"], "retained size", len(data))
    need(descriptor["sha256"] == digest(data), "retained hash differs: " + expected)
    return decode(data)


def words(value, count, label):
    need(type(value) is list and len(value) == count
         and all(type(word) is str and WORD.fullmatch(word) for word in value), label + " words differ")
    return value


def source_identity(root, report):
    before = identified(root, report["source_before"], "snapshots/source-before.json")
    after = identified(root, report["source_after"], "snapshots/source-after.json")
    same(before, after, "source snapshots")
    checkout = before["checkout"]
    need(checkout["dirty"] is False and checkout["blockers"] == []
         and checkout["changed_paths"] == [] and checkout["untracked_paths"] == [], "source was not clean")
    for key in ("revision", "tree"):
        need(type(checkout[key]) is str and COMMIT.fullmatch(checkout[key]), "invalid source " + key)
    return checkout


def completed_report(report, contract):
    uint(report["schema_version"], "report schema", 1)
    need(report["contract_id"] == contract and report["state"] == "finished"
         and report["outcome"] == "pass" and report["development"] is False
         and report["source_stable"] is True and report["acceptance_claimed"] is False
         and report["phase_complete"] is False and report["reason"] is None
         and not report.get("failure_reasons") and not report.get("resource_snapshot_error"),
         "failed, incomplete, unstable or unsupported report")
    uint(report["iterations"], "report iterations", 2)
    need(not any(key in report for key in ("scope", "evidence_level", "full_matrix_verified", "phase_acceptance")),
         "report adds an unsupported scope/acceptance declaration")


def command_log(root, command):
    data = read_file(member(root, command["log"]))
    uint(command["log_size_bytes"], "command log size", len(data))
    need(command["log_sha256"] == digest(data), "command log hash differs")
    text = data.decode("utf-8")
    need(not any((ord(c) < 32 and c not in "\t\r\n") or 127 <= ord(c) <= 159 for c in text),
         "log contains control characters")
    return text


def commands(root, report, expected_ids, numerical_ids):
    rows = report["commands"]
    need(type(rows) is list and 1 <= len(rows) <= 128, "command inventory size differs")
    result = {}
    for row in rows:
        identifier = row["id"]
        need(type(identifier) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,160}", identifier)
             and identifier not in result, "invalid/duplicate command ID")
        need(row["outcome"] == "pass" and row["process_started"] is True
             and row["cleanup_complete"] is True, "unsuccessful retained command: " + identifier)
        uint(row["exit_code"], "command exit", 0)
        need(type(row["argv"]) is list and 1 <= len(row["argv"]) <= 128
             and all(type(arg) is str and len(arg) <= 8192 and "\x00" not in arg for arg in row["argv"]),
             "invalid command argv")
        same(row["log"], "logs/" + identifier + ".log", "command log path")
        result[identifier] = row
    logs = plain(root / "logs", directory=True)
    names = []
    for entry in logs.iterdir():
        need(len(names) < 128, "extra retained log files")
        plain(entry)
        names.append(entry.name)
    need(set(names) == {identifier + ".log" for identifier in result}, "missing or extra command logs")
    need(set(result) == expected_ids, "command membership differs from the frozen execution contract")
    for identifier, row in result.items():
        text = command_log(root, row)
        if identifier not in numerical_ids:
            need(not re.search(r"\bP0[345]_(?:RESULT|MATMUL|MODEL|REJECTIONS)(?=\s|$)", text, re.I),
                 "numerical observation in an unauthorized command log: " + identifier)
    return result


def raw_rows(root, command, markers, native=False):
    text = command_log(root, command)
    need(not re.search(r"\b(?:FAILED|FAIL|ERROR|FATAL|ABORTED|MISMATCH)\b|P0[345]_FAILURE|"
                       r"Segmentation fault|runtime error:", text, re.I), "log contains failure diagnostics")
    lines = text.splitlines()
    if native:
        need(lines and lines[-1] == "PASSED!" and lines.count("PASSED!") == 1
             and len(re.findall(r"\bPASSED\b", text, re.I)) == 1, "ambiguous native completion marker")
    rows, sequence, rejections = {marker: [] for marker in markers}, [], 0
    for line in lines:
        if not re.search(r"P0[345]_", line, re.I):
            continue
        if markers == ("P03_RESULT",) and line == "P03_REJECTIONS checked=2":
            rejections += 1
            continue
        marker = line.split(" ", 1)[0]
        need(marker in rows and line.startswith(marker + " "), "malformed or extra observation marker")
        need(len(sequence) < (16 if markers == ("P05_MATMUL", "P05_MODEL") else 2), "extra raw observations")
        payload = line[len(marker) + 1:].encode("utf-8")
        need(len(payload) <= RECORD_LIMIT, "observation record exceeds byte bound")
        rows[marker].append(decode(payload, observations=True))
        sequence.append(marker)
    need(rejections == (1 if markers == ("P03_RESULT",) else 0), "native rejection marker count differs")
    return rows, sequence


def native_options(command, case_id, binding, revision=None):
    argv = command["argv"]
    keys = {"--case", "--iterations", "--module", "--qualification-id"}
    if revision is not None:
        keys |= {"--backend", "--source-revision"}
    need(len(argv) == 1 + 2 * len(keys), "native argv count differs")
    options = dict(zip(argv[1::2], argv[2::2]))
    need(set(options) == keys and len(options) == len(keys), "duplicate/extra native options")
    need(options["--case"] == case_id and options["--iterations"] == "2"
         and options["--qualification-id"] == binding, "native invocation differs")
    if revision is not None:
        need(options["--source-revision"] == revision and options["--backend"] == "simx",
             "native model invocation source/scope differs")


def status(value, python=False, submission=False):
    fields(value, STATUS, "execution status")
    if python:
        need(value["validation"] == "success", "Python native validation failed")
    else:
        uint(value["validation"], "native validation", 0)
    uint(value["primary"], "primary status", 0)
    uint(value["cleanup"], "cleanup status", 0)
    need(type(value["complete"]) is bool and (submission or value["complete"]), "incomplete native owner")


def wire(dispatch, shape, fmt, iteration):
    m, n, k = shape
    for key, size in zip(("a_bytes", "b_bytes", "d_bytes"), (m*k*2, k*n*2, m*n*4)):
        uint(dispatch[key], key, size)
    uint(dispatch["poison"], "destination poison", POISONS[iteration])
    addresses = [uint(dispatch[key], key) for key in ("a_address", "b_address", "d_address")]
    sizes = (m*k*2, k*n*2, m*n*4)
    spans = [(address, address + size) for address, size in zip(addresses, sizes)]
    need(all(start % 4 == 0 and end <= 1 << 64 for start, end in spans), "invalid operand span")
    need(all(a[1] <= b[0] or b[1] <= a[0] for i, a in enumerate(spans) for b in spans[i+1:]),
         "operand spans overlap")
    expected = struct.pack("<8I3Q", 1, 56, 1 if fmt == "fp16" else 2, 0, m, n, k, 0, *addresses).hex()
    same(dispatch["argument_bytes"], expected, "observed wire arguments")


def dispatch(value, shape, fmt, iteration, binding):
    fields(value, DISPATCH, "profiled dispatch")
    for key in DISPATCH_NUMBERS:
        uint(value[key], "dispatch." + key)
    same([value[k] for k in ("m", "n", "k")], list(shape), "dispatch geometry")
    need(value["qualification_id"] == binding and value["input_dtype"] == fmt, "dispatch binding differs")
    wire(value, shape, fmt, iteration)
    for key, expected in (("writes_enqueued", 3), ("launches_enqueued", 1), ("reads_enqueued", 1)):
        uint(value[key], key, expected)
    need(value["wait_calls"] > value["timed_out_waits"], "no completed native wait")
    need(value["profiling_enabled"] is True, "missing profiled dispatch")
    same(value["event_results"], [0] * 5, "event results")
    same(value["event_profile_results"], [0] * 5, "profile results")
    same(value["event_profile_queried"], [True] * 5, "profile query inventory")
    need(type(value["event_profiles"]) is list and len(value["event_profiles"]) == 5,
         "missing or extra event profiles")
    for profile in value["event_profiles"]:
        fields(profile, {"queued_ns", "submit_ns", "start_ns", "end_ns"}, "event profile")
        for key, number_value in profile.items():
            uint(number_value, key)
    return len(value["event_profiles"])


def matmul(row, case, iteration, binding, python=False):
    if python:
        fields(row, {"case_id", "iteration", "status", "close_status", "actual_bits", "trace", "resources"},
               "installed matmul")
        status(row["status"], python=True)
        status(row["close_status"], python=True)
        profiles = dispatch(row["trace"], tuple(case[k] for k in ("m", "n", "k")),
                            case["format"], iteration, binding)
    else:
        fields(row, {"case_id", "format", "m", "n", "k", "iteration", "checked", "mismatches",
                     "actual_bits", "qualification_id", "dispatch", "resources"}, "native matmul")
        need(row["format"] == case["format"] and row["qualification_id"] == binding, "native matmul identity differs")
        for key in ("m", "n", "k"):
            uint(row[key], "native " + key, case[key])
        uint(row["checked"], "native checked count", case["m"] * case["n"])
        uint(row["mismatches"], "native mismatch count", 0)
        value = row["dispatch"]
        fields(value, {"a_address", "b_address", "d_address", "a_bytes", "b_bytes", "d_bytes",
                       "writes", "reads", "launches", "waits", "poison", "argument_bytes"}, "P03 dispatch")
        wire(value, tuple(case[k] for k in ("m", "n", "k")), case["format"], iteration)
        for key, expected in (("writes", 3), ("reads", 1), ("launches", 1)):
            uint(value[key], key, expected)
        need(uint(value["waits"], "native waits") > 0, "missing native wait")
        profiles = 0
    need(row["case_id"] == case["id"], "matmul membership differs")
    uint(row["iteration"], "matmul iteration", iteration)
    actual = words(row["actual_bits"], case["m"] * case["n"], "actual matmul")
    same(actual, case["expected"], "actual matmul versus frozen expected bits")
    resources = row["resources"]
    keys = {"used_before", "used_after", "free_before", "free_after"}
    status_keys = {"before_status", "after_status"} if python else {"primary", "cleanup"}
    fields(resources, keys | status_keys, "matmul resources")
    for key, value in resources.items():
        uint(value, "resource " + key, 0 if key in status_keys else None)
    need(resources["used_before"] == resources["used_after"] and resources["free_before"] == resources["free_after"],
         "matmul resources did not return to baseline")
    return {"matmul_runs": 1, "matmul_launches": 1, "matmul_words": len(actual), "event_profile_pairs": profiles}


def model(record, oracle, iteration, binding, revision, helper):
    fields(record, RESULT, "model record")
    need(record["clock"] == "std::chrono::steady_clock" and record["timing_scope"] == "host_runtime_observations",
         "unsupported model timing scope")
    trace = record["trace"]
    fields(trace, TRACE, "model trace")
    for key in TRACE_TIMES:
        uint(trace[key], key)
    fields(trace["resources"], {"before_valid", "after_valid", "before_status", "after_status",
                               "free_before", "used_before", "free_after", "used_after"}, "model resources")
    resource = trace["resources"]
    need(resource["before_valid"] is True and resource["after_valid"] is True, "missing model resources")
    for key in ("before_status", "after_status", "free_before", "used_before", "free_after", "used_after"):
        uint(resource[key], key, 0 if key.endswith("status") else None)
    need(resource["free_before"] == resource["free_after"] and resource["used_before"] == resource["used_after"],
         "model resources did not return to baseline")
    fields(trace["result"], {"status", "execution", "terminal"}, "model result")
    status(trace["result"]["execution"])
    status(trace["owner_cleanup"])
    need(type(trace["native"]) is list and len(trace["native"]) == 3, "model stage inventory differs")
    profiles = 0
    for index, stage in enumerate(trace["native"]):
        fields(stage, STAGE, "model stage")
        for key in STAGE_TIMES:
            uint(stage[key], key)
        status(stage["submission"], submission=True)
        status(stage["completion"])
        status(stage["cleanup"])
        profiles += dispatch(stage["dispatch"], ((16, 8, 16), (8, 4, 8), (8, 4, 8))[index],
                             oracle["case"]["format"], iteration, binding)
    helper.observed(record, oracle, "simx", revision, binding, iteration)
    return {"model_runs": 1, "model_launches": len(trace["native"]),
            "model_hidden_words": len(trace["native"][0]["output_words"]),
            "model_bridge_words": len(trace["bridge_words"]),
            "model_output_block_words": sum(len(stage["output_words"]) for stage in trace["native"][1:]),
            "model_output_words": len(trace["output_words"]), "event_profile_pairs": profiles}


def add(counts, values):
    for key, value in values.items():
        counts[key] = counts.get(key, 0) + value


def fixtures(source):
    documents = {}
    for name, expected in FIXTURES.items():
        data = read_file(source / "ci/project/fixtures" / name, 1024 * 1024)
        need(digest(data) == expected, "frozen fixture differs: " + name)
        documents[name] = decode(data, observations=True)
    all_matmuls = [dict(case, **case["dimensions"]) for name in list(FIXTURES)[:2]
                  for case in documents[name]["cases"]]
    need(len(all_matmuls) == 88 and len({case["id"] for case in all_matmuls}) == 88, "P02 fixture inventory differs")
    indexed = {case["id"]: case for case in all_matmuls}
    selected = {fmt: [indexed[fmt + "-" + name] for name, _ in SELECTION] for fmt in FORMATS}
    for fmt in FORMATS:
        for case, (_, shape) in zip(selected[fmt], SELECTION):
            need(case["format"] == fmt and tuple(case[k] for k in ("m", "n", "k")) == shape,
                 "frozen selected signature differs")
    helper_bytes = read_file(source / HELPER, 64 * 1024)
    need(digest(helper_bytes) == HELPER_SHA256, "accepted P04 numerical helper differs")
    spec = importlib.util.spec_from_file_location("accepted_p04_numerics", source / HELPER)
    helper = importlib.util.module_from_spec(spec)
    exec(compile(helper_bytes, str(source / HELPER), "exec"), helper.__dict__)
    oracles, peaks = helper.fixture_oracles(source / "ci/project/fixtures/p04_tiny_mlp_v1.json")
    data = documents["p04_tiny_mlp_v1.json"]
    models = {fmt: [dict(case, w1_words=data["weights"]["formats"][fmt]["w1_words"],
                        w2_words=data["weights"]["formats"][fmt]["w2_words"])
                    for case in data["cases"] if case["format"] == fmt] for fmt in FORMATS}
    return selected, models, oracles, peaks, helper


def packet(root, selected, model_cases, oracles, helper):
    plain(root, directory=True)
    report_data = read_file(root / "report.json")
    report = decode(report_data)
    completed_report(report, "p05-installed-python-execution-v1")
    fmt = report["format"]
    need(fmt in FORMATS and report["backend"] == "simx", "unsupported P05 variant")
    need("full_matrix_requested" not in report, "single-format P05 report adds an unsupported matrix claim")
    checkout = source_identity(root, report)
    revision = checkout["revision"]
    cases = selected[fmt]
    models = model_cases[fmt]
    matmul_ids, model_ids = [case["id"] for case in cases], [case["id"] for case in models]
    numerical_ids = {"native-" + name for name in matmul_ids} | {"installed-matrix"}
    command_map = commands(root, report, numerical_ids | {
        "package-tools-before", "native-matmul-build", "native-matmul-effective-header",
        "package-bound-sdist", "package-offline-wheel", "package-create-venv",
        "package-install-wheel", "package-tools-after"}, numerical_ids)
    same(report["matmul_case_ids"], matmul_ids, "reported matmul membership")
    same(report["model_case_ids"], model_ids, "reported model membership")
    same(identified(root, report["selection"], "snapshots/selection.json"),
         {"matmuls": cases, "models": models}, "retained selection versus frozen inputs")
    request = identified(root, report["installed_request"], "snapshots/installed-request.json")
    fields(request, {"schema_version", "contract_id", "binding", "matmul_cases", "model_cases",
                     "iterations", "expected_prefix"}, "installed request")
    uint(request["schema_version"], "request schema", 1)
    uint(request["iterations"], "request iterations", 2)
    need(request["contract_id"] == "p05-installed-request-v1", "request contract differs")
    same(request["matmul_cases"], cases, "requested frozen matmuls")
    same(request["model_cases"], model_ids, "requested model membership")
    binding = request["binding"]
    fields(binding, BINDING, "installed binding")
    for key in ("bundle_sha256", "source_sha256", "qualification_id"):
        need(type(binding[key]) is str and HEX.fullmatch(binding[key]), "invalid " + key)
    need(binding["backend"] == "simx" and binding["format"] == fmt and binding["source_revision"] == revision,
         "installed request source/variant differs")
    native_id = binding["qualification_id"]
    need(report["native_qualification_id"] == native_id, "native/Python model identity differs")
    native = identified(root, report["native_report"], "native/report.json")
    completed_report(native, "p04-managed-model-execution-v1")
    same(source_identity(root / "native", native), checkout, "native and Python source identity")
    need(native["fixture_sha256"] == FIXTURES["p04_tiny_mlp_v1.json"]
         and native["full_matrix_requested"] is False, "native fixture or matrix scope differs")
    same(native["case_ids"], model_ids, "native model membership")
    same(identified(root / "native", native["fixture_snapshot"], "snapshots/fixtures.json"), models,
         "native frozen inputs")
    need(type(native["variants"]) is list and len(native["variants"]) == 1, "native variant inventory differs")
    variant = native["variants"][0]
    need(variant["id"] == "simx-" + fmt and variant["backend"] == "simx" and variant["format"] == fmt
         and variant["qualification_id"] == native_id and variant["outcome"] == "pass", "native variant differs")
    for packet_root, descriptor, path, expected_id in (
            (root, report["matmul_binding"], "snapshots/native-matmul-binding.json", report["matmul_qualification_id"]),
            (root / "native", variant["binding"], "snapshots/simx-" + fmt + "-binding.json", native_id)):
        value = identified(packet_root, descriptor, path)
        need(type(expected_id) is str and HEX.fullmatch(expected_id) and digest(canonical(value)) == expected_id,
             "native binding digest differs")
        same(value["source"], checkout, "native binding source")
        need(value["backend"] == "simx" and value["format"] == fmt, "native binding scope differs")
    native_numerical_ids = {"simx-" + fmt + "-" + name for name in model_ids}
    native_commands = commands(root / "native", native, native_numerical_ids | {
        "version-gpp", "version-clang", "version-make"} | {
        "simx-" + fmt + "-" + suffix for suffix in (
            "configure", "header", "cpp-header-reproduce", "verilog-header-reproduce",
            "runtime", "application", "effective-header")}, native_numerical_ids)
    need([case["id"] for case in variant["cases"]] == model_ids, "native cases missing, duplicated or extra")
    need([case["id"] for case in report["native_matmuls"]] == matmul_ids,
         "native matmuls missing, duplicated or extra")
    for case in variant["cases"]:
        fields(case, {"id", "outcome", "observations"}, "native model case")
    for case in report["native_matmuls"]:
        fields(case, {"id", "observations"}, "native matmul case")
    expected_commands = {"native-" + name for name in matmul_ids}
    need({key for key, row in command_map.items() if "--case" in row["argv"]} == expected_commands,
         "unaccounted native matmul command")
    need({key for key, row in native_commands.items() if "--case" in row["argv"]}
         == {"simx-" + fmt + "-" + name for name in model_ids}, "unaccounted native model command")
    observed = identified(root, report["observations"], "artifacts/installed-observations.json")
    fields(observed, {"schema_version", "contract_id", "scope", "binding", "installation", "matmuls",
                      "models", "counts", "outcome", "acceptance_claimed"}, "installed observations")
    uint(observed["schema_version"], "observations schema", 1)
    need(observed["contract_id"] == "p05-installed-observations-v1" and observed["scope"] == "simx-installed-python"
         and observed["outcome"] == "pass" and observed["acceptance_claimed"] is False,
         "failed or unsupported installed observations")
    same(observed["binding"], binding, "installed observed binding")
    installed_raw, sequence = raw_rows(root, command_map["installed-matrix"], ("P05_MATMUL", "P05_MODEL"))
    same(sequence, ["P05_MATMUL"] * 6 + ["P05_MODEL"] * 10, "installed observation chronology")
    same(installed_raw["P05_MATMUL"], observed["matmuls"], "installed matmul log/file")
    same(installed_raw["P05_MODEL"], observed["models"], "installed model log/file")
    counts = {"python": {}, "native": {}}
    for index, case in enumerate(cases):
        command = command_map["native-" + case["id"]]
        native_options(command, case["id"], report["matmul_qualification_id"])
        rows, _ = raw_rows(root, command, ("P03_RESULT",), native=True)
        rows = rows["P03_RESULT"]
        need(len(rows) == 2, "native matmul repetitions differ")
        same(rows, report["native_matmuls"][index]["observations"], "native matmul raw/report")
        for iteration, row in enumerate(rows):
            python_row = observed["matmuls"][index * 2 + iteration]
            add(counts["native"], matmul(row, case, iteration, report["matmul_qualification_id"]))
            add(counts["python"], matmul(python_row, case, iteration, native_id, python=True))
            same(python_row["actual_bits"], row["actual_bits"], "installed/native matmul actual bits")
    for index, case in enumerate(models):
        saved = variant["cases"][index]
        need(saved["outcome"] == "pass", "failed native model case")
        command = native_commands["simx-" + fmt + "-" + case["id"]]
        native_options(command, case["id"], native_id, revision)
        rows, _ = raw_rows(root / "native", command, ("P04_RESULT",), native=True)
        rows = rows["P04_RESULT"]
        need(len(rows) == 2, "native model repetitions differ")
        same(rows, saved["observations"], "native model raw/report")
        for iteration, row in enumerate(rows):
            python_row = observed["models"][index * 2 + iteration]
            fields(python_row, {"case_id", "iteration", "record"}, "installed model")
            need(python_row["case_id"] == case["id"], "installed model membership differs")
            uint(python_row["iteration"], "installed model iteration", iteration)
            python_record = python_row["record"]
            for route, record in (("native", row), ("python", python_record)):
                add(counts[route], model(record, oracles[case["id"]], iteration, native_id, revision, helper))
            for key in ("hidden_words", "bridge_words", "bridge_bytes", "output_words"):
                same(python_record["trace"][key], row["trace"][key], "installed/native actual " + key)
            for left, right in zip(python_record["trace"]["native"], row["trace"]["native"]):
                for key in ("a_bytes", "b_bytes", "output_words"):
                    same(left[key], right[key], "installed/native stage " + key)
    for route in counts:
        counts[route]["total_launches"] = counts[route]["matmul_launches"] + counts[route]["model_launches"]
    summary_keys = ("matmul_runs", "model_runs", "matmul_launches", "model_launches", "total_launches")
    supplied = {key: counts["python"][key] for key in summary_keys}
    same(observed["counts"], supplied, "supplied installed counts")
    same(report["comparison"]["counts"], supplied, "reported installed counts")
    same(report["native_counts"], {key: counts["native"][key] for key in summary_keys}, "reported native counts")
    for key in ("matmul_words", "model_hidden_words", "model_bridge_words", "model_output_words", "event_profile_pairs"):
        uint(report["comparison"][key], "reported comparison " + key, counts["python"][key])
    uint(report["completed_native_and_python_launches"], "combined launch count",
         counts["native"]["total_launches"] + counts["python"]["total_launches"])
    uint(native["completed_case_executions"], "native case count", len(models))
    uint(native["completed_model_runs"], "native model run count", counts["native"]["model_runs"])
    uint(native["completed_launches"], "native model launch count", counts["native"]["model_launches"])
    same(native["comparison_counts"], {
        "hidden_words": counts["native"]["model_hidden_words"],
        "bridge_words": counts["native"]["model_bridge_words"],
        "output_block_words": counts["native"]["model_output_block_words"],
        "assembled_output_words": counts["native"]["model_output_words"]}, "native comparison counts")
    return {"path": str(root), "report_sha256": digest(report_data), "format": fmt,
            "source_revision": revision, "source_tree": checkout["tree"],
            "source_checkout_sha256": digest(canonical(checkout)),
            "source_snapshot_sha256": report["source_before"]["sha256"],
            "native_report_sha256": report["native_report"]["sha256"],
            "observations_sha256": report["observations"]["sha256"],
            "native_qualification_id": native_id, "matmul_qualification_id": report["matmul_qualification_id"],
            "matmul_case_ids": matmul_ids, "model_case_ids": model_ids, "counts": counts}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--packet", required=True, action="append", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--selected-scope", action="store_true")
    args = parser.parse_args(argv)
    try:
        need(args.output.is_absolute(), "output must be absolute")
        plain(args.output.parent, directory=True)
        need(not os.path.lexists(args.output), "output must be fresh")
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    READS.clear()
    result = {"schema_version": 1, "audit": "independent-p05-retained-numerics-v1", "outcome": "fail",
              "execution_performed_by_audit": False, "phase_acceptance": False,
              "full_matrix_verified": False, "selected_scope_requested": args.selected_scope,
              "packets": [], "fixture_sha256": FIXTURES,
              "reused_helper": {"path": HELPER, "sha256": HELPER_SHA256,
                                "functions": ["fixture_oracles", "observed"],
                                "purpose": "Accepted P04 independent integer mathematics and live hidden/bridge/stage lineage; no P05 helper imports."},
              "limitations": ["Retained-data audit only; it does not execute or authenticate a native backend.",
                              "Source/build/package provenance and dispatch/timing review remain complementary obligations.",
                              "P02 standalone inputs are identified by frozen requests and native source provenance; their logs do not retain uploaded operand contents.",
                              "Only the selected six signatures and ten fixed model cases on SimX are in scope; no complete P03 rerun, RTL, physical performance or framework claim.",
                              "Trusted-builder/nonadversarial-filesystem scope; archives are not opened or extracted."]}
    try:
        plain(args.source_dir, directory=True)
        need(len(args.packet) in ((1, 2) if args.selected_scope else (2,)), "two format packets required unless --selected-scope")
        need(len(set(args.packet)) == len(args.packet), "duplicate packet directory")
        selected, models, oracles, peaks, helper = fixtures(args.source_dir)
        result["accumulation_prefix_peaks"] = peaks
        result["auditor_sha256"] = digest(read_file(Path(__file__).absolute(), 128 * 1024))
        for root in args.packet:
            result["packets"].append(packet(root, selected, models, oracles, helper))
        packets = result["packets"]
        formats = [row["format"] for row in packets]
        need(len(set(formats)) == len(formats), "duplicate packet format")
        identities = {(row["source_revision"], row["source_tree"], row["source_checkout_sha256"]) for row in packets}
        need(len(identities) == 1, "packets mix source revision/tree")
        full = set(formats) == set(FORMATS)
        need(full or args.selected_scope, "incomplete format matrix")
        result.update(full_matrix_verified=full, matrix_scope="complete" if full else "incomplete_selected_format",
                      source_revision=packets[0]["source_revision"], source_tree=packets[0]["source_tree"],
                      variants=["simx-" + fmt for fmt in formats], counts={"python": {}, "native": {}})
        for row in packets:
            for route in result["counts"]:
                add(result["counts"][route], row["counts"][route])
        result["total_launches"] = sum(count["total_launches"] for count in result["counts"].values())
        result["event_profile_pairs"] = sum(count["event_profile_pairs"] for count in result["counts"].values())
        result["outcome"] = "pass"
    except (OSError, ValueError, KeyError, TypeError, IndexError, OverflowError, RecursionError) as error:
        result["reason"] = type(error).__name__ + ": " + str(error)
    result["inputs"] = list(READS.values())
    text = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    try:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(text)
    except OSError as error:
        print("could not retain audit result: " + str(error), file=sys.stderr)
        return 2
    print(json.dumps({"outcome": result["outcome"], "output": str(args.output),
                      "reason": result.get("reason"), "full_matrix_verified": result["full_matrix_verified"]}))
    return 0 if result["outcome"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
