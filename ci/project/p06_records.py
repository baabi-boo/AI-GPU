# SPDX-License-Identifier: Apache-2.0
"""Validate whole-context benchmark observations; parsing never executes a GPU."""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math
import re
import statistics

import p02_wmma_fixtures as operator_fixtures
import p03_execution_records as operator_records
import p04_execution_records as model_records
import p04_fixture_adapter as model_fixtures
import p06_contract as manifest


ROOT = manifest.ROOT
MAX_LOG_BYTES = 16 * 1024 * 1024
MAX_RECORD_BYTES = 256 * 1024
MAX_JSON_DEPTH = 16
UINT64_MAX = (1 << 64) - 1
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
REVISION = re.compile(r"[0-9a-f]{40}\Z")
SAMPLE_KEYS = {"sample_id", "workload_id", "phase", "repetition", "command_id",
               "outcome", "process_duration_seconds", "observation"}
OBSERVATION_KEYS = {
    "schema_version", "contract_id", "sample_id", "workload_id", "binding_id",
    "source_revision", "fixture_sha256", "raw_log_sha256", "numerical_results",
    "snapshots", "release", "counter_deltas", "accounting", "dispatch_counts",
    "host_timings_ns", "boundaries",
}
COUNTER_FIELDS = {"name", "mpm_class", "csr", "core_id", "scope", "unit", "required_isa"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _fields(value, keys, label):
    _require(type(value) is dict and set(value) == set(keys),
             label + ": missing or unknown fields")


def _same(actual, expected, label):
    """Keep booleans, integer values and floating point values distinct."""
    _require(type(actual) is type(expected), label + ": incorrect value type")
    if type(expected) is dict:
        _fields(actual, expected, label)
        for key, value in expected.items():
            _same(actual[key], value, label + "." + key)
    elif type(expected) is list:
        _require(len(actual) == len(expected), label + ": incorrect inventory size")
        for index, value in enumerate(expected):
            _same(actual[index], value, label + "[" + str(index) + "]")
    else:
        _require(actual == expected, label + ": value differs")


def _uint(value, label):
    _require(type(value) is int and 0 <= value <= UINT64_MAX,
             label + ": expected uint64")
    return value


def _identifier(value, pattern, label):
    _require(type(value) is str and pattern.fullmatch(value), "invalid " + label)


def _unique(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value, "duplicate JSON field: " + key)
        value[key] = item
    return value


def _integer(token):
    _require(len(token) <= 20 and not token.startswith("-"),
             "JSON integer exceeds unsigned bounds")
    return _uint(int(token), "JSON integer")


def _noninteger(_):
    raise ValueError("record numbers must be unsigned integers")


def _json(payload):
    _require(len(payload.encode("utf-8")) <= MAX_RECORD_BYTES,
             "record exceeds its byte bound")
    depth = 0
    quoted = escaped = False
    for character in payload:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in "[{":
            depth += 1
            _require(depth <= MAX_JSON_DEPTH, "record exceeds its nesting bound")
        elif character in "]}":
            depth -= 1
    try:
        result = json.loads(payload, object_pairs_hook=_unique, parse_int=_integer,
                            parse_float=_noninteger, parse_constant=_noninteger)
    except (RecursionError, OverflowError) as error:
        raise ValueError("record exceeds JSON parser bounds") from error
    _require(type(result) is dict, "record must contain one JSON object")
    return result


def _workload(contract, workload):
    choices = manifest.select_workloads(contract)
    _require(type(workload) is dict and type(workload.get("id")) is str,
             "invalid workload")
    expected = next((row for row in choices if row["id"] == workload["id"]), None)
    _require(expected is not None, "unknown workload")
    _same(workload, expected, "workload")


def _case(workload, contract):
    pins = {row["path"]: row["sha256"] for row in contract["source_inputs"]}
    data = manifest._read_file(ROOT / workload["fixture"], manifest.MAX_SOURCE_BYTES)
    _require(hashlib.sha256(data).hexdigest() == pins[workload["fixture"]]
             == workload["fixture_sha256"], "fixture differs from its frozen source pin")
    cases = (operator_fixtures.load_cases(ROOT) if workload["kind"] == "matmul"
             else model_fixtures.load_cases(ROOT))
    selected = [case for case in cases if case["id"] == workload["case_id"]]
    _require(len(selected) == 1 and selected[0]["format"] == workload["format"],
             "independent fixture identity differs")
    return selected[0]


def _identity(workload, binding_id, sample_id, source_revision, fixture_sha256, contract):
    _workload(contract, workload)
    _identifier(binding_id, SHA256, "execution binding")
    _identifier(source_revision, REVISION, "source revision")
    _identifier(fixture_sha256, SHA256, "fixture digest")
    _identifier(sample_id, re.compile(contract["observation"]["sample_id_pattern"]),
                "sample identity")
    _require(fixture_sha256 == workload["fixture_sha256"],
             "sample fixture digest differs from the frozen workload")


def _records(text, workload, contract):
    _require(type(text) is str and len(text) <= MAX_LOG_BYTES, "missing or oversized log")
    try:
        encoded = text.encode("utf-8", errors="strict")
    except UnicodeError as error:
        raise ValueError("log is not valid UTF-8") from error
    _require(len(encoded) <= MAX_LOG_BYTES, "log exceeds its byte bound")
    _require(not any((ord(char) < 32 and char not in "\t\n\r")
                     or 127 <= ord(char) <= 159 or char in "\u2028\u2029" for char in text),
             "log contains control or ambiguous line separator characters")
    _require(not re.search(r"\b(?:FAILED|FAIL|ERROR|FATAL|ABORTED|MISMATCH)\b|"
                           r"P0[346]_FAILURE|Segmentation fault|runtime error:",
                           text, re.IGNORECASE), "log contains a failure")
    lines = text.splitlines()
    _require(lines and lines[-1] == "PASSED!" and lines.count("PASSED!") == 1
             and len(re.findall(r"\bPASSED\b", text, re.IGNORECASE)) == 1,
             "missing or ambiguous final success record")
    order = contract["observation"]["marker_order"][workload["kind"]]
    markers = set(order) - {"PASSED!"}
    found, positions, observed = {}, {}, []
    rejection_position = None
    for index, line in enumerate(lines):
        _require(len(line.encode("utf-8")) <= MAX_RECORD_BYTES, "log line exceeds its byte bound")
        if line == "PASSED!":
            observed.append(line)
            continue
        if line == "P03_REJECTIONS checked=2":
            _require(workload["kind"] == "matmul" and rejection_position is None,
                     "unexpected or duplicate operator rejection check")
            rejection_position = index
            continue
        marker = next((name for name in markers if line.startswith(name + " ")), None)
        if marker is not None:
            _require(marker not in found, "duplicate record marker: " + marker)
            found[marker] = _json(line[len(marker) + 1:])
            positions[marker] = index
            observed.append(marker)
        else:
            _require(not re.search(r"P0[346]", line, re.IGNORECASE),
                     "unknown, malformed or wrong-route record marker")
    _same(observed, order, "record chronology")
    if workload["kind"] == "matmul":
        _require(rejection_position is not None
                 and positions["P06_BEGIN"] < rejection_position < positions["P03_RESULT"],
                 "missing or reordered operator rejection check")
    return found, hashlib.sha256(encoded).hexdigest()


def _snapshot(snapshot, *, sample_id, contract, label):
    observation = contract["observation"]
    _fields(snapshot, observation["snapshot_keys"], label)
    for key, expected in (("schema_version", 1), ("sample_id", sample_id),
                          ("context_id", observation["context_id"]),
                          ("device_index", observation["device_index"]),
                          ("compiled_memory_block_bytes",
                           contract["geometry"]["compiled_memory_block_bytes"])):
        _same(snapshot[key], expected, label + "." + key)
    begin = _uint(snapshot["query_begin_ns"], label + ".query_begin_ns")
    end = _uint(snapshot["query_end_ns"], label + ".query_end_ns")
    _require(begin <= end, "snapshot query timestamps are reversed")
    capabilities = snapshot["capabilities"]
    _require(type(capabilities) is list and len(capabilities) == len(contract["capabilities"]),
             "incorrect capability inventory")
    for actual, descriptor in zip(capabilities, contract["capabilities"]):
        _same(actual, {**descriptor, "status": 0,
                       "value": contract["capability_values"][descriptor["name"]]},
              label + ".capability." + descriptor["name"])
    counters = snapshot["counters"]
    _require(type(counters) is list and len(counters) == len(contract["counters"]),
             "incorrect counter inventory")
    isa = contract["capability_values"]["isa_flags"]
    for actual, descriptor in zip(counters, contract["counters"]):
        name = descriptor["name"]
        _fields(actual, COUNTER_FIELDS | {"enabled", "status", "value"}, label + "." + name)
        for key in COUNTER_FIELDS:
            _same(actual[key], descriptor[key], label + "." + name + "." + key)
        required = descriptor["required_isa"]
        enabled = required == 0 or (isa & required) == required
        _same(actual["enabled"], enabled, label + "." + name + ".enabled")
        if enabled:
            _same(actual["status"], 0, label + "." + name + ".status")
            _uint(actual["value"], label + "." + name + ".value")
        else:
            _require(actual["status"] is None and actual["value"] is None,
                     "disabled counter must have unavailable status and value")


def _lifetime(snapshots, release, *, sample_id, contract):
    _fields(snapshots, {"begin", "end"}, "snapshots")
    before, after = snapshots["begin"], snapshots["end"]
    _snapshot(before, sample_id=sample_id, contract=contract, label="begin")
    _snapshot(after, sample_id=sample_id, contract=contract, label="end")
    _require(before["query_end_ns"] <= after["query_begin_ns"],
             "snapshot intervals overlap or are reversed")
    _same(release, {"schema_version": 1, "sample_id": sample_id,
                    "context_id": contract["observation"]["context_id"], "status": 0},
          "actual device release")
    deltas = []
    for first, last in zip(before["counters"], after["counters"]):
        value = None
        if first["enabled"]:
            _require(last["value"] >= first["value"],
                     "counter decreased or wrapped: " + first["name"])
            value = last["value"] - first["value"]
            if first["name"] in contract["observation"]["positive_counter_deltas"]:
                _require(value > 0, "nonempty workload lacks positive " + first["name"])
        deltas.append({**{key: first[key] for key in sorted(COUNTER_FIELDS)},
                       "available": first["enabled"], "value": value})
    return deltas


def _numerical(text, workload, binding_id, source_revision, fixture_sha256, contract):
    case = _case(workload, contract)
    if workload["kind"] == "matmul":
        return operator_records.verify_output(text, case, 1, binding_id)
    return model_records.verify_output(text, case, 1, binding_id, backend="simx",
                                       source_revision=source_revision,
                                       fixture_sha256=fixture_sha256)


def _accounting(numerical, workload):
    row = numerical[0]
    model = workload["kind"] == "mlp"
    if model:
        trace = row["trace"]
        dispatches = [stage["dispatch"] for stage in trace["native"]]
        shapes = [[dispatch[key] for key in ("m", "n", "k")] for dispatch in dispatches]
        writes, reads, launches, waits = (sum(d[key] for d in dispatches) for key in
                                        ("writes_enqueued", "reads_enqueued",
                                         "launches_enqueued", "wait_calls"))
    else:
        dispatches = [row["dispatch"]]
        shapes = [[row[key] for key in ("m", "n", "k")]]
        writes, reads, launches, waits = (row["dispatch"][key]
                                         for key in ("writes", "reads", "launches", "waits"))
    _same(shapes, workload["native_shapes"], "actual native shape inventory")
    _same(launches, workload["expected_launches"], "actual launch count")
    inputs = sum(d["a_bytes"] + d["b_bytes"] for d in dispatches)
    outputs = sum(d["d_bytes"] for d in dispatches)
    macs = sum(m * n * k for m, n, k in shapes)
    accounting = {
        "macs": macs, "flops": 2 * macs, "input_h2d_bytes": inputs,
        "poison_h2d_bytes": outputs, "tensor_h2d_bytes": inputs + outputs,
        "tensor_d2h_bytes": outputs,
        "argument_payload_bytes": sum(len(bytes.fromhex(d["argument_bytes"])) for d in dispatches),
        "host_relu_elements": len(trace["hidden_words"]) if model else 0,
        "host_cast_elements": len(trace["hidden_words"]) if model else 0,
        "host_bridge_input_bytes": 4 * len(trace["hidden_words"]) if model else 0,
        "host_bridge_output_bytes": len(bytes.fromhex(trace["bridge_bytes"])) if model else 0,
        "host_assembly_bytes": 4 * len(trace["output_words"]) if model else 0,
    }
    _same(accounting, workload["accounting"], "dimension and dispatch accounting")
    counts = {"launches": launches, "input_writes": 2 * launches,
              "poison_writes": launches, "tensor_writes": writes,
              "tensor_reads": reads, "wait_calls": waits,
              "intentional_rejections": 0 if model else 2}
    return accounting, counts


def _host_timings(numerical, snapshots, workload):
    before, after = snapshots["begin"], snapshots["end"]
    values = {"observer_begin_query": before["query_end_ns"] - before["query_begin_ns"],
              "observer_end_query": after["query_end_ns"] - after["query_begin_ns"]}
    if workload["kind"] == "mlp":
        trace = numerical[0]["trace"]
        _require(trace["create_begin_ns"] <= before["query_begin_ns"]
                 <= before["query_end_ns"] <= trace["create_end_ns"],
                 "initial observer interval is outside model creation")
        last_stage = trace["native"][-1]
        last_event_end = last_stage["dispatch"]["event_profiles"][-1]["end_ns"]
        _require(max(last_stage["submit_end_ns"], last_event_end) <= after["query_begin_ns"],
                 "final observer interval precedes completed native work")
        _require(values["observer_end_query"] <= trace["close_ns"],
                 "final query duration exceeds its enclosing model close duration")
        advance = trace["advance_ns"]
        _require(advance <= after["query_begin_ns"] - trace["create_end_ns"],
                 "model advance duration exceeds its enclosing lifetime")
        serial_advance = 0
        for name in ("bridge", "bridge_compare", "assembly", "output_compare"):
            _require(trace[name + "_ns"] <= advance,
                     "model " + name + " duration exceeds its enclosing advance duration")
            serial_advance += trace[name + "_ns"]
        values["model_create"] = trace["create_end_ns"] - trace["create_begin_ns"]
        for name in ("advance", "bridge", "bridge_compare", "assembly", "output_compare", "close"):
            values["model_" + name] = trace[name + "_ns"]
        for index, stage in enumerate(trace["native"]):
            prefix = "native_stage_" + str(index) + "_"
            values[prefix + "submit"] = stage["submit_end_ns"] - stage["submit_begin_ns"]
            _require(values[prefix + "submit"] <= advance,
                     "native submit duration exceeds its enclosing model advance duration")
            serial_advance += values[prefix + "submit"]
            for name in ("wait", "compare", "close"):
                _require(stage[name + "_ns"] <= advance,
                         "native " + name + " duration exceeds its enclosing model advance duration")
                values[prefix + name] = stage[name + "_ns"]
                serial_advance += stage[name + "_ns"]
        # Successful advance serializes these host scopes; event profiles overlap them.
        _require(serial_advance <= advance,
                 "serial model work exceeds its enclosing advance duration")
    return values


def _observation(numerical, snapshots, release, *, workload, binding_id, sample_id,
                 source_revision, fixture_sha256, contract, raw_log_sha256):
    deltas = _lifetime(snapshots, release, sample_id=sample_id, contract=contract)
    accounting, counts = _accounting(numerical, workload)
    timings = _host_timings(numerical, snapshots, workload)
    return deepcopy({
        "schema_version": 1, "contract_id": contract["contract_id"],
        "sample_id": sample_id, "workload_id": workload["id"], "binding_id": binding_id,
        "source_revision": source_revision, "fixture_sha256": fixture_sha256,
        "raw_log_sha256": raw_log_sha256, "numerical_results": numerical,
        "snapshots": snapshots, "release": release, "counter_deltas": deltas,
        "accounting": accounting, "dispatch_counts": counts, "host_timings_ns": timings,
        "boundaries": contract["boundaries"],
    })


def verify_sample(text, workload, binding_id, *, sample_id, source_revision,
                  fixture_sha256, contract):
    """Check the original, unfiltered log and retain its actual numerical records.

    The caller also has to bind this log to a successful bounded-process receipt,
    immutable artifacts and qualified compiler/configuration records. Counter
    consistency alone does not establish execution provenance or acceptance.
    """
    _identity(workload, binding_id, sample_id, source_revision, fixture_sha256, contract)
    raw, digest = _records(text, workload, contract)
    numerical = _numerical(text, workload, binding_id, source_revision, fixture_sha256, contract)
    marker = "P03_RESULT" if workload["kind"] == "matmul" else "P04_RESULT"
    _same(numerical, [raw[marker]], "original numerical result")
    return _observation(numerical, {"begin": raw["P06_BEGIN"], "end": raw["P06_END"]},
                        raw["P06_RELEASE"], workload=workload, binding_id=binding_id,
                        sample_id=sample_id, source_revision=source_revision,
                        fixture_sha256=fixture_sha256, contract=contract, raw_log_sha256=digest)


def _recheck(observation, workload, sample_id, contract):
    """Recompute stored derivations without treating them as authoritative data.

    Re-serialized numerical rows below only recheck their retained semantics.
    They do not replace verification of the original complete log or its digest.
    """
    _fields(observation, OBSERVATION_KEYS, "sample observation")
    _identifier(observation["raw_log_sha256"], SHA256, "raw log digest")
    _identity(workload, observation["binding_id"], sample_id, observation["source_revision"],
              observation["fixture_sha256"], contract)
    numerical = observation["numerical_results"]
    _require(type(numerical) is list and len(numerical) == 1, "incorrect retained numerical inventory")
    marker = "P03_RESULT" if workload["kind"] == "matmul" else "P04_RESULT"
    try:
        payload = json.dumps(numerical[0], separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError("invalid retained numerical record") from error
    parsed = _json(payload)
    _same(numerical[0], parsed, "retained numerical JSON types")
    checked = _numerical(marker + " " + payload + "\nPASSED!\n", workload,
                         observation["binding_id"], observation["source_revision"],
                         observation["fixture_sha256"], contract)
    recomputed = _observation(checked, observation["snapshots"], observation["release"],
                              workload=workload, binding_id=observation["binding_id"],
                              sample_id=sample_id, source_revision=observation["source_revision"],
                              fixture_sha256=observation["fixture_sha256"], contract=contract,
                              raw_log_sha256=observation["raw_log_sha256"])
    _same(observation, recomputed, "retained observation")


def _statistics(values):
    return {"count": len(values), "minimum": min(values), "maximum": max(values),
            "median": statistics.median(values), "population_stddev": statistics.pstdev(values)}


def summarize(samples, contract, workloads):
    """Require the complete selected-format inventory; reduce measurements only."""
    _require(type(workloads) is list and workloads, "empty or invalid workload selection")
    _require(all(type(workload) is dict and type(workload.get("format")) is str
                 for workload in workloads), "invalid selected workload")
    formats = list(dict.fromkeys(workload["format"] for workload in workloads))
    selected = manifest.select_workloads(contract, formats)
    _same(workloads, selected, "canonical selected workload inventory")
    policy = contract["sampling"]
    sequence = [(workload, phase, repetition) for workload in selected
                for phase, count in (("warmup", policy["warmup_runs"]),
                                     ("measurement", policy["measured_runs"]))
                for repetition in range(count)]
    _require(type(samples) is list and len(samples) == len(sequence),
             "incomplete or extra sample inventory")
    command_ids, log_digests, revisions = set(), set(), set()
    bindings = {}
    per_workload = {workload["id"]: [] for workload in selected}
    for sample, (workload, phase, repetition) in zip(samples, sequence):
        _fields(sample, SAMPLE_KEYS, "sample")
        sample_id = workload["id"] + "-" + phase + "-" + str(repetition)
        for key, expected in (("sample_id", sample_id), ("workload_id", workload["id"]),
                              ("phase", phase), ("repetition", repetition), ("outcome", "pass")):
            _same(sample[key], expected, "sample." + key)
        command_id = sample["command_id"]
        _require(type(command_id) is str and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,255}", command_id)
                 and command_id not in command_ids, "invalid or duplicate command receipt identity")
        command_ids.add(command_id)
        duration = sample["process_duration_seconds"]
        _require(type(duration) in (int, float)
                 and 0 <= duration <= contract["budget"]["run_timeout_seconds"] + 10
                 and math.isfinite(duration),
                 "invalid bounded-process duration")
        observation = sample["observation"]
        _recheck(observation, workload, sample_id, contract)
        _require(observation["raw_log_sha256"] not in log_digests,
                 "samples reuse a raw log digest despite distinct sample identities")
        log_digests.add(observation["raw_log_sha256"])
        previous_binding = bindings.setdefault(workload["format"], observation["binding_id"])
        _require(observation["binding_id"] == previous_binding,
                 "samples mix execution bindings within a format")
        snapshots = observation["snapshots"]
        first_observation = (observation["numerical_results"][0]["trace"]["create_begin_ns"]
                             if workload["kind"] == "mlp" else snapshots["begin"]["query_begin_ns"])
        context_interval = snapshots["end"]["query_end_ns"] - first_observation
        # The bounded runner rounds wall duration to six fractional digits.
        # This tolerance accounts for that rounding, not for removing overhead.
        # Interpret the retained decimal exactly: binary float multiplication
        # can place an exact allowance boundary just below its integer value.
        process_bound_ns = Fraction(str(duration)) * 1_000_000_000 + 1000
        _require(max(context_interval, *observation["host_timings_ns"].values())
                 <= process_bound_ns,
                 "retained host interval exceeds the whole process duration")
        if workload["kind"] == "mlp":
            # Creation, accumulated advances and accumulated closes are disjoint.
            lifecycle = sum(observation["host_timings_ns"]["model_" + name]
                            for name in ("create", "advance", "close"))
            _require(lifecycle <= process_bound_ns,
                     "serial model lifecycle exceeds the whole process duration")
        revisions.add(observation["source_revision"])
        if phase == "measurement":
            per_workload[workload["id"]].append(sample)
    _require(len(revisions) == 1, "samples mix source revisions")
    summaries = []
    for workload in selected:
        rows = per_workload[workload["id"]]
        observations = [row["observation"] for row in rows]
        counter_statistics = []
        for index, descriptor in enumerate(contract["counters"]):
            first = observations[0]["counter_deltas"][index]
            values = [row["counter_deltas"][index]["value"] for row in observations]
            counter_statistics.append({**descriptor, "available": first["available"],
                                       "statistics": _statistics(values) if first["available"] else None})
        summaries.append({
            "workload_id": workload["id"], "format": workload["format"], "kind": workload["kind"],
            "warmup_sample_ids": [workload["id"] + "-warmup-0"],
            "measured_sample_ids": [row["sample_id"] for row in rows],
            "accounting_per_invocation": deepcopy(workload["accounting"]),
            "counter_statistics": counter_statistics,
            "process_duration_seconds": _statistics([row["process_duration_seconds"] for row in rows]),
            "host_timings_ns": {name: _statistics([row["host_timings_ns"][name] for row in observations])
                                for name in observations[0]["host_timings_ns"]},
            "dispatch_counts": {name: _statistics([row["dispatch_counts"][name] for row in observations])
                                for name in observations[0]["dispatch_counts"]},
        })
    launches = sum(workload["expected_launches"] for workload in selected)
    warmups, measurements = policy["warmup_runs"], policy["measured_runs"]
    inventory = {"workloads": len(selected), "warmup_processes": len(selected) * warmups,
                 "measured_processes": len(selected) * measurements, "total_processes": len(samples),
                 "warmup_launches": launches * warmups, "measured_launches": launches * measurements,
                 "total_launches": launches * (warmups + measurements)}
    full_matrix = formats == contract["formats"]
    if full_matrix:
        _same(inventory, contract["inventory"], "full matrix inventory")
    return {"schema_version": 1, "contract_id": contract["contract_id"],
            "source_revision": next(iter(revisions)), "formats": formats,
            "full_matrix": full_matrix, "acceptance_claimed": False,
            "inventory": inventory, "sampling": deepcopy(policy), "workloads": summaries,
            "boundaries": deepcopy(contract["boundaries"]),
            "limitations": deepcopy(contract["limitations"])}
