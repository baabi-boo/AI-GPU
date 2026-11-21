#!/usr/bin/env python3
"""Independently reconcile original P06 archive measurements without executing them."""

import argparse
import collections
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import statistics
import sys
import zipfile


REVISION = "84b6ca0ca75fba248ba330642bbf8764db3d459c"
EVIDENCE = "docs/project/evidence/p06-baseline"
CONTRACT = "ci/project/p06_benchmark_contract.json"
MAX_MEMBER_BYTES = 64 * 1024 * 1024
COUNTER_KEYS = {"name", "mpm_class", "csr", "core_id", "scope", "unit", "required_isa"}


class AuditError(ValueError):
    """An original measurement does not match its frozen contract."""


def require(condition, message):
    if not condition:
        raise AuditError(message)


def same(actual, expected, label):
    require(type(actual) is type(expected), label + ": type differs")
    if isinstance(expected, dict):
        require(actual.keys() == expected.keys(), label + ": fields differ")
        for key in expected:
            same(actual[key], expected[key], label + "." + key)
    elif isinstance(expected, list):
        require(len(actual) == len(expected), label + ": count differs")
        for index, value in enumerate(expected):
            same(actual[index], value, label + "[" + str(index) + "]")
    else:
        require(actual == expected, label + ": value differs")


def uint(value, label):
    require(type(value) is int and 0 <= value < 2**64, label + ": expected uint64")
    return value


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field: " + key)
        result[key] = value
    return result


def reject_constant(value):
    raise AuditError("nonfinite JSON number: " + value)


def document(body):
    return json.loads(body, object_pairs_hook=unique_pairs, parse_constant=reject_constant)


def sha256(body):
    return hashlib.sha256(body).hexdigest()


def relative_path(value):
    require(type(value) is str and value and "\\" not in value,
            "invalid relative path")
    path = PurePosixPath(value)
    require(not path.is_absolute() and all(part not in ("", ".", "..")
                                           for part in value.split("/")),
            "unsafe relative path: " + value)
    return path


def repo_path(repo, value):
    path = (repo / relative_path(value)).resolve()
    require(path.is_relative_to(repo), "path escapes repository: " + value)
    return path


def member(archive, path):
    name = str(relative_path(path))
    info = archive.getinfo(name)
    require(not info.is_dir() and info.file_size <= MAX_MEMBER_BYTES,
            "invalid or oversized archive member: " + name)
    return archive.read(info)


def snapshot(archive, descriptor):
    body = member(archive, "baseline/" + str(relative_path(descriptor["path"])))
    same(len(body), descriptor["size_bytes"], "snapshot size")
    same(sha256(body), descriptor["sha256"], "snapshot digest")
    return document(body)


def exactly_one(lines, marker):
    values = [document(line[len(marker):]) for line in lines if line.startswith(marker)]
    require(len(values) == 1, "expected exactly one " + marker)
    return values[0]


def words_bytes(words):
    require(type(words) is list and all(type(word) is str
            and re.fullmatch(r"[0-9a-f]{8}", word) for word in words),
            "invalid frozen uint32 words")
    return b"".join(int(word, 16).to_bytes(4, "little") for word in words).hex()


def stats(values):
    require(values, "empty statistics input")
    return {"count": len(values), "minimum": min(values), "maximum": max(values),
            "median": statistics.median(values),
            "population_stddev": statistics.pstdev(values)}


def counters(begin, end, observed, contract, sample_id):
    expected_capabilities = [{**row, "status": 0,
                              "value": contract["capability_values"][row["name"]]}
                             for row in contract["capabilities"]]
    for point in (begin, end):
        same(set(point), set(contract["observation"]["snapshot_keys"]), "snapshot fields")
        for key, value in (("schema_version", 1), ("sample_id", sample_id),
                           ("context_id", contract["observation"]["context_id"]),
                           ("device_index", contract["observation"]["device_index"]),
                           ("compiled_memory_block_bytes",
                            contract["geometry"]["compiled_memory_block_bytes"]),
                           ("capabilities", expected_capabilities)):
            same(point[key], value, "snapshot." + key)
        require(uint(point["query_begin_ns"], "query begin")
                <= uint(point["query_end_ns"], "query end"), "reversed query interval")
        same(len(point["counters"]), 45, "snapshot counter count")
    require(begin["query_end_ns"] <= end["query_begin_ns"], "overlapping snapshots")
    same(len(observed), 45, "retained counter delta count")
    values, deltas = {}, []
    isa_flags = contract["capability_values"]["isa_flags"]
    for descriptor, first, last in zip(contract["counters"], begin["counters"], end["counters"]):
        identity = {key: descriptor[key] for key in COUNTER_KEYS}
        mask = descriptor["required_isa"]
        enabled = mask == 0 or (isa_flags & mask) == mask
        for row in (first, last):
            same(set(row), COUNTER_KEYS | {"enabled", "status", "value"}, "counter fields")
            same({key: row[key] for key in COUNTER_KEYS}, identity, "counter descriptor")
            same(row["enabled"], enabled, "counter availability")
            same(row["status"], 0 if enabled else None, "counter status")
            if enabled:
                uint(row["value"], "counter value")
            else:
                same(row["value"], None, "disabled counter value")
        value = None
        if enabled:
            require(last["value"] >= first["value"], "counter decreased or wrapped")
            value = last["value"] - first["value"]
            if descriptor["name"] in contract["observation"]["positive_counter_deltas"]:
                require(value > 0, "nonpositive required counter delta")
        deltas.append({**identity, "available": enabled, "value": value})
        values[descriptor["name"]] = value
    same(observed, deltas, "raw counter subtraction")
    same(sum(value is not None for value in values.values()), 33, "available counters")
    return values, deltas


def resources(row, model):
    for before, after in (("free_before", "free_after"), ("used_before", "used_after")):
        uint(row[before], before)
        same(row[after], row[before], "resource restoration")
    if model:
        for key in ("before_status", "after_status"):
            same(row[key], 0, "resource query status")
        for key in ("before_valid", "after_valid"):
            same(row[key], True, "resource query validity")
    else:
        same(row["primary"], 0, "matmul primary status")
        same(row["cleanup"], 0, "matmul cleanup status")


def numerical(row, workload, case, fixture, binding_id):
    same(row["qualification_id"], binding_id, "numerical binding")
    same(row["iteration"], 0, "numerical iteration")
    native_words = bridge_words = assembled_words = 0
    model = workload["kind"] == "mlp"
    if not model:
        for key, expected in (("case_id", case["id"]), ("format", workload["format"]),
                              ("m", workload["m"]), ("n", workload["n"]),
                              ("k", workload["k"]), ("mismatches", 0),
                              ("checked", len(case["expected"])),
                              ("actual_bits", case["expected"])):
            same(row[key], expected, "matmul." + key)
        resources(row["resources"], False)
        native_words = len(row["actual_bits"])
        dispatches = [row["dispatch"]]
    else:
        for key, expected in (("source_revision", REVISION), ("backend", "simx"),
                              ("fixture_sha256", workload["fixture_sha256"]),
                              ("fixture_id", fixture["fixture_id"]),
                              ("model_id", fixture["model_id"])):
            same(row[key], expected, "model." + key)
        trace = row["trace"]
        for key, expected in (("case_id", case["id"]), ("input_dtype", workload["format"]),
                              ("hidden_words", case["hidden_words"]),
                              ("bridge_words", case["bridge_words"]),
                              ("output_words", case["output_words"]),
                              ("bridge_bytes", words_bytes(case["bridge_words"])),
                              ("bridge_checked_words", len(case["bridge_words"])),
                              ("output_checked_words", len(case["output_words"])),
                              ("bridge_mismatches", 0), ("output_mismatches", 0),
                              ("bridge_status", 0)):
            same(trace[key], expected, "model trace." + key)
        for key in ("hidden_valid", "bridge_attempted", "bridge_compared", "bridge_valid",
                    "assembled", "logits_compared", "logits_valid", "owner_closed"):
            same(trace[key], True, "model trace." + key)
        complete = {"cleanup": 0, "complete": True, "primary": 0, "validation": 0}
        same(trace["owner_cleanup"], complete, "model owner cleanup")
        same(trace["result"], {"execution": complete, "status": "success", "terminal": True},
             "model terminal result")
        resources(trace["resources"], True)
        same(len(trace["native"]), 3, "model native stage count")
        expected_outputs = [case["hidden_words"], case["output_words"][:32],
                            case["output_words"][32:]]
        bridge = words_bytes(case["bridge_words"])
        expected_inputs = [words_bytes(case["input_words"]), bridge[:len(bridge) // 2],
                           bridge[len(bridge) // 2:]]
        weights = fixture["weights"]["formats"][workload["format"]]
        expected_weights = [words_bytes(weights["w1_words"]),
                            words_bytes(weights["w2_words"]),
                            words_bytes(weights["w2_words"])]
        for index, (stage, expected_output) in enumerate(zip(trace["native"], expected_outputs)):
            for key, expected in (("sequence", index), ("output_words", expected_output),
                                  ("checked_words", len(expected_output)), ("mismatches", 0),
                                  ("a_bytes", expected_inputs[index]),
                                  ("b_bytes", expected_weights[index]),
                                  ("completion", complete), ("cleanup", complete)):
                same(stage[key], expected, "native stage." + key)
            for key in ("submitted", "waited", "compared", "closed", "trace_valid", "output_valid"):
                same(stage[key], True, "native stage." + key)
            dispatch = stage["dispatch"]
            same(dispatch["qualification_id"], binding_id, "native stage binding")
            same(dispatch["input_dtype"], workload["format"], "native stage format")
            same([dispatch[key] for key in ("m", "n", "k")], workload["native_shapes"][index],
                 "native stage shape")
            same(dispatch["event_results"], [0] * 5, "native event results")
            same(dispatch["event_profile_results"], [0] * 5, "native profile results")
            same(dispatch["event_profile_queried"], [True] * 5, "native profile queries")
            same(dispatch["timed_out_waits"], 0, "native timed-out waits")
            native_words += len(stage["output_words"])
        bridge_words, assembled_words = len(case["bridge_words"]), len(case["output_words"])
        dispatches = [stage["dispatch"] for stage in trace["native"]]
    for dispatch, (m, n, k) in zip(dispatches, workload["native_shapes"]):
        for key, expected in (("a_bytes", m * k * 2), ("b_bytes", k * n * 2),
                              ("d_bytes", m * n * 4)):
            same(dispatch[key], expected, "native buffer size")
        keys = (("launches_enqueued", "writes_enqueued", "reads_enqueued", "wait_calls")
                if model else ("launches", "writes", "reads", "waits"))
        same([dispatch[key] for key in keys], [1, 3, 1, 1], "native dispatch counts")
        same(len(bytes.fromhex(dispatch["argument_bytes"])), 56, "native argument size")
    launches = len(dispatches)
    same(launches, workload["expected_launches"], "actual launch count")
    inputs = sum(dispatch["a_bytes"] + dispatch["b_bytes"] for dispatch in dispatches)
    outputs = sum(dispatch["d_bytes"] for dispatch in dispatches)
    macs = sum(m * n * k for m, n, k in workload["native_shapes"])
    accounting = {"macs": macs, "flops": 2 * macs, "input_h2d_bytes": inputs,
                  "poison_h2d_bytes": outputs, "tensor_h2d_bytes": inputs + outputs,
                  "tensor_d2h_bytes": outputs, "argument_payload_bytes": 56 * launches,
                  "host_relu_elements": len(case["hidden_words"]) if model else 0,
                  "host_cast_elements": len(case["hidden_words"]) if model else 0,
                  "host_bridge_input_bytes": 4 * len(case["hidden_words"]) if model else 0,
                  "host_bridge_output_bytes": bridge_words * 4,
                  "host_assembly_bytes": assembled_words * 4}
    same(accounting, workload["accounting"], "frozen accounting")
    counts = {"launches": launches, "input_writes": 2 * launches, "poison_writes": launches,
              "tensor_writes": 3 * launches, "tensor_reads": launches, "wait_calls": launches,
              "intentional_rejections": 0 if model else 2}
    return accounting, counts, native_words, bridge_words, assembled_words


def host_timings(row, begin, end, duration, model):
    timings = {"observer_begin_query": begin["query_end_ns"] - begin["query_begin_ns"],
               "observer_end_query": end["query_end_ns"] - end["query_begin_ns"]}
    start = begin["query_begin_ns"]
    if model:
        trace = row["trace"]
        start = uint(trace["create_begin_ns"], "model creation begin")
        require(start <= begin["query_begin_ns"] <= begin["query_end_ns"]
                <= uint(trace["create_end_ns"], "model creation end"),
                "initial snapshot is outside model creation")
        timings["model_create"] = trace["create_end_ns"] - start
        for name in ("advance", "bridge", "bridge_compare", "assembly", "output_compare", "close"):
            timings["model_" + name] = uint(trace[name + "_ns"], "model " + name)
        for index, stage in enumerate(trace["native"]):
            prefix = "native_stage_" + str(index) + "_"
            require(uint(stage["submit_begin_ns"], "stage submit begin")
                    <= uint(stage["submit_end_ns"], "stage submit end"),
                    "reversed stage submission")
            timings[prefix + "submit"] = stage["submit_end_ns"] - stage["submit_begin_ns"]
            for name in ("wait", "compare", "close"):
                timings[prefix + name] = uint(stage[name + "_ns"], "stage " + name)
    context_ns = end["query_end_ns"] - start
    # The microsecond allowance covers receipt rounding, never monitor subtraction.
    require(0 <= max(context_ns, *timings.values())
            <= Fraction(str(duration)) * 1_000_000_000 + 1000,
            "host interval exceeds the retained process duration")
    return timings, context_ns / 1_000_000_000


def summarize(groups, selected, contract, fmt):
    workloads = []
    for workload in selected:
        samples = groups[workload["id"]]
        measured = [row for row in samples if row["phase"] == "measurement"]
        same(len(measured), 5, "measured sample count")
        counter_statistics = []
        for descriptor in contract["counters"]:
            values = [row["counter_values"][descriptor["name"]] for row in measured]
            available = values[0] is not None
            counter_statistics.append({**descriptor, "available": available,
                                       "statistics": stats(values) if available else None})
        workloads.append({
            "workload_id": workload["id"], "format": fmt, "kind": workload["kind"],
            "warmup_sample_ids": [row["sample_id"] for row in samples if row["phase"] == "warmup"],
            "measured_sample_ids": [row["sample_id"] for row in measured],
            "accounting_per_invocation": workload["accounting"],
            "counter_statistics": counter_statistics,
            "process_duration_seconds": stats([row["process_duration_seconds"] for row in measured]),
            "host_timings_ns": {name: stats([row["host_timings_ns"][name] for row in measured])
                                for name in measured[0]["host_timings_ns"]},
            "dispatch_counts": {name: stats([row["dispatch_counts"][name] for row in measured])
                                for name in measured[0]["dispatch_counts"]}})
    return {"schema_version": 1, "contract_id": contract["contract_id"],
            "source_revision": REVISION, "formats": [fmt], "full_matrix": False,
            "acceptance_claimed": False,
            "inventory": {"workloads": 4, "warmup_processes": 4, "measured_processes": 20,
                          "total_processes": 24, "warmup_launches": 6,
                          "measured_launches": 30, "total_launches": 36},
            "sampling": contract["sampling"], "workloads": workloads,
            "boundaries": contract["boundaries"], "limitations": contract["limitations"]}


def audit_format(repo, entry, contract, contract_digest, fixtures):
    fmt = entry["format"]
    archive_bytes = repo_path(repo, entry["path"]).read_bytes()
    same(len(archive_bytes), entry["size_bytes"], "original archive size")
    same(sha256(archive_bytes), entry["sha256"], "external archive digest")
    selected = [workload for workload in contract["workloads"] if workload["format"] == fmt]
    same(len(selected), 4, "format workload count")
    expected = [{"workload_id": workload["id"], "phase": phase, "repetition": repetition,
                 "sample_id": workload["id"] + "-" + phase + "-" + str(repetition)}
                for workload in selected for phase, count in (("warmup", 1), ("measurement", 5))
                for repetition in range(count)]
    result = {"archive_path": entry["path"], "archive_sha256": entry["sha256"],
              "samples": [], "workloads": {}, "counts": collections.Counter()}
    groups = collections.defaultdict(list)
    # Opening the bytes already hashed avoids replacing the path between hash and read.
    import io
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "duplicate archive member")
        report = document(member(archive, "baseline/report.json"))
        for key, value in (("outcome", "pass"), ("state", "finished"), ("failures", []),
                           ("completed_samples", 24), ("formats", [fmt]),
                           ("expected_samples", expected), ("sampling", contract["sampling"]),
                           ("workload_ids", [workload["id"] for workload in selected]),
                           ("contract_sha256", contract_digest)):
            same(report[key], value, "report." + key)
        same(snapshot(archive, report["contract_snapshot"]), contract, "frozen contract snapshot")
        same(snapshot(archive, report["workload_snapshot"]), selected, "selected workload snapshot")
        same(len(report["samples"]), 24, "raw sample inventory")
        command_map = {command["id"]: command for command in report["commands"]}
        same(len(command_map), len(report["commands"]), "unique command identities")
        command_ids, log_digests, bindings = set(), set(), set()
        by_id = {workload["id"]: workload for workload in selected}
        for sample, identity in zip(report["samples"], expected):
            sample_id = identity["sample_id"]
            workload = by_id[identity["workload_id"]]
            for key, value in {**identity, "outcome": "pass"}.items():
                same(sample[key], value, sample_id + "." + key)
            require(sample["command_id"] not in command_ids, "reused sample command")
            command_ids.add(sample["command_id"])
            command = command_map[sample["command_id"]]
            for key, value in (("outcome", "pass"), ("exit_code", 0), ("cleanup_complete", True),
                               ("process_started", True), ("reason", None)):
                same(command[key], value, sample_id + ".command." + key)
            same(command["environment"]["P06_SAMPLE_ID"], sample_id, "command sample environment")
            duration = command["duration_seconds"]
            require(type(duration) in (int, float) and math.isfinite(duration)
                    and 0 <= duration <= contract["budget"]["run_timeout_seconds"] + 10,
                    "invalid process duration")
            same(sample["process_duration_seconds"], duration, "retained process duration")
            raw = member(archive, "baseline/" + str(relative_path(command["log"])))
            digest = sha256(raw)
            same(digest, command["log_sha256"], "raw sample log digest")
            same(len(raw), command["log_size_bytes"], "raw sample log size")
            require(digest not in log_digests, "reused sample log")
            log_digests.add(digest)
            lines = raw.decode("utf-8").splitlines()
            require(lines.count("PASSED!") == 1 and lines[-1] == "PASSED!",
                    "missing unique final success marker")
            require(not any(line.startswith("P06_FAILURE") for line in lines), "raw failure marker")
            marker = "P03_RESULT" if workload["kind"] == "matmul" else "P04_RESULT"
            order = contract["observation"]["marker_order"][workload["kind"]]
            positions = [next(index for index, line in enumerate(lines)
                              if line == name or line.startswith(name + " ")) for name in order]
            require(positions == sorted(positions), "raw marker order")
            begin, end, release, row = [exactly_one(lines, name + " ")
                                        for name in ("P06_BEGIN", "P06_END", "P06_RELEASE", marker)]
            observed = sample["observation"]
            for key, value in (("sample_id", sample_id), ("workload_id", workload["id"]),
                               ("source_revision", REVISION), ("fixture_sha256", workload["fixture_sha256"]),
                               ("contract_id", contract["contract_id"]), ("raw_log_sha256", digest),
                               ("snapshots", {"begin": begin, "end": end}), ("release", release),
                               ("numerical_results", [row]), ("boundaries", contract["boundaries"])):
                same(observed[key], value, sample_id + ".observation." + key)
            same(release, {"schema_version": 1, "sample_id": sample_id,
                           "context_id": contract["observation"]["context_id"], "status": 0},
                 "actual device release")
            counter_values, _ = counters(begin, end, observed["counter_deltas"], contract, sample_id)
            fixture = fixtures[workload["fixture"]]
            cases = [case for case in fixture["cases"] if case["id"] == workload["case_id"]]
            same(len(cases), 1, "unique frozen numerical case")
            binding_id = observed["binding_id"]
            require(type(binding_id) is str and re.fullmatch(r"[0-9a-f]{64}", binding_id),
                    "invalid numerical binding")
            bindings.add(binding_id)
            accounting, dispatch, native_words, bridge_words, assembled_words = numerical(
                row, workload, cases[0], fixture, binding_id)
            if workload["kind"] == "matmul":
                same(lines.count("P03_REJECTIONS checked=2"), 1, "intentional rejection count")
            same(observed["accounting"], accounting, "raw accounting")
            same(observed["dispatch_counts"], dispatch, "raw dispatch counts")
            timings, context = host_timings(row, begin, end, duration, workload["kind"] == "mlp")
            same(observed["host_timings_ns"], timings, "raw host timings")
            audited = {**identity, "process_duration_seconds": duration,
                       "observed_context_seconds": context, "counter_values": counter_values,
                       "host_timings_ns": timings, "dispatch_counts": dispatch,
                       "raw_log_sha256": digest, "cleanup_complete": True}
            groups[workload["id"]].append(audited)
            result["samples"].append(audited)
            for key, value in {"processes": 1, "launches": dispatch["launches"],
                               "native_output_words": native_words, "host_bridge_words": bridge_words,
                               "assembled_output_words": assembled_words}.items():
                result["counts"][key] += value
                result["counts"][identity["phase"] + "_" + key] += value
        same(len(bindings), 1, "one execution binding per format")
        summary = summarize(groups, selected, contract, fmt)
        same(report["summary"], summary, "independent measured-only summary")
        same(snapshot(archive, report["summary_snapshot"]), summary, "retained summary snapshot")
        result["summary_verified"] = True
        result["summary_snapshot_sha256"] = report["summary_snapshot"]["sha256"]
        for workload_id, samples in groups.items():
            measured = [sample for sample in samples if sample["phase"] == "measurement"]
            varying = [name for name in samples[0]["counter_values"]
                       if len({sample["counter_values"][name] for sample in samples}) > 1]
            result["workloads"][workload_id] = {
                "all_six_counter_samples_identical": not varying, "varying_counters": varying,
                "cycles": measured[0]["counter_values"]["cycles"],
                "instructions": measured[0]["counter_values"]["instructions"],
                "process_duration_seconds": stats([sample["process_duration_seconds"] for sample in measured]),
                "observed_context_seconds": stats([sample["observed_context_seconds"] for sample in measured])}
    return result


def audit(repo):
    index_body = repo_path(repo, EVIDENCE + "/archive-index.json").read_bytes()
    index = document(index_body)
    same(index["repository"], "baabi-boo/AI-GPU", "archive repository")
    same(index["source_revision"], REVISION, "original source revision")
    same([entry["format"] for entry in index["archives"]], ["fp16", "bf16"], "archive format inventory")
    contract_body = repo_path(repo, CONTRACT).read_bytes()
    contract = document(contract_body)
    same(contract["formats"], ["fp16", "bf16"], "frozen format inventory")
    same(len(contract["workloads"]), 8, "frozen workload inventory")
    same(len(contract["counters"]), 45, "frozen counter inventory")
    same(contract["sampling"]["warmup_runs"], 1, "frozen warmup count")
    same(contract["sampling"]["measured_runs"], 5, "frozen measured count")
    fixtures, fixture_digests = {}, {}
    for workload in contract["workloads"]:
        path = workload["fixture"]
        if path not in fixtures:
            body = repo_path(repo, path).read_bytes()
            fixture_digests[path] = sha256(body)
            fixtures[path] = document(body)
        same(fixture_digests[path], workload["fixture_sha256"], "frozen fixture digest")
    result = {"schema_version": 1,
              "scope": "independent original raw numerical, counter and summary reconciliation",
              "source_revision": REVISION, "native_execution": "not_run",
              "archive_code_executed": False, "acceptance_claimed": False,
              "archive_index_sha256": sha256(index_body), "contract_sha256": sha256(contract_body),
              "fixture_sha256": fixture_digests, "formats": {}, "totals": collections.Counter()}
    for entry in index["archives"]:
        same(entry["path"], EVIDENCE + "/archives/simx-" + entry["format"] + ".zip", "original archive path")
        reviewed = audit_format(repo, entry, contract, sha256(contract_body), fixtures)
        result["formats"][entry["format"]] = reviewed
        result["totals"].update(reviewed["counts"])
    for key, expected in (("processes", 48), ("launches", 72), ("measurement_processes", 40),
                           ("measurement_launches", 60), ("native_output_words", 4608),
                           ("host_bridge_words", 768), ("assembled_output_words", 768)):
        same(result["totals"][key], expected, "full matrix " + key)
    result["outcome"] = "pass"
    result["limitations"] = [
        "Compares original raw words with existing independent frozen fixtures; does not regenerate their arithmetic.",
        "Reads original ZIP members as data without extraction, importing archive helpers, or executing archive code or binaries.",
        "Archive identity is checked against the supplied archive index; this audit does not independently authenticate GitHub origin or rebuild source.",
        "Native execution belongs to the archived source revision; this data audit is not a new native execution or an acceptance decision.",
        "Whole-context SimX counters cannot identify individual model-stage costs or physical speed, bandwidth, power or energy.",
        "Retained process duration includes supervisor monitoring and cleanup latency; no exact process-exit timestamp was retained, so that delay cannot be removed retrospectively.",
        "No observer, nested host interval or estimated supervisor delay is subtracted from retained process duration.",
        "Warmup is a separate fresh process and does not warm later device contexts; summaries use all five measurement samples without outlier removal.",
        "P06-A02/A03, vendor integration, native RTL performance, synthesis and physical hardware measurements remain separate obligations.",
    ]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path, help="Repository containing the original evidence and frozen fixtures")
    parser.add_argument("--output", required=True, type=Path, help="New JSON review path; existing files are never overwritten")
    args = parser.parse_args()
    try:
        require(not args.output.exists() and not args.output.is_symlink(), "output already exists")
        result = audit(args.repo.resolve())
        payload = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        with args.output.open("x", encoding="utf-8") as output:
            output.write(payload)
        print(json.dumps({"outcome": "pass", "totals": result["totals"], "report": str(args.output)}))
        return 0
    except (AuditError, OSError, KeyError, TypeError, ValueError, StopIteration, zipfile.BadZipFile) as error:
        print(json.dumps({"outcome": "fail", "reason": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
