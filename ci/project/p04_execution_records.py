# SPDX-License-Identifier: Apache-2.0
"""Check model observations against trusted fixtures; parsing is not execution."""

from __future__ import annotations

import json
import re
import struct

from p02_matrix_records import require


MAX_LOG_BYTES = 16 * 1024 * 1024
MAX_RECORD_BYTES = 256 * 1024
UINT64_MAX = (1 << 64) - 1
WORD = re.compile(r"[0-9a-f]{8}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
RESULT_KEYS = {
    "schema_version", "model_id", "fixture_id", "fixture_sha256", "source_revision",
    "backend", "iteration", "qualification_id", "clock", "timing_scope", "trace",
}
EXECUTION_KEYS = {"validation", "primary", "cleanup", "complete"}
MODEL_RESULT_KEYS = {"status", "execution", "terminal"}
TRACE_FLAGS = {
    "hidden_valid", "bridge_attempted", "bridge_valid", "bridge_compared", "assembled",
    "logits_valid", "logits_compared", "owner_closed",
}
TRACE_TIMES = {
    "create_begin_ns", "create_end_ns", "advance_ns", "bridge_ns", "bridge_compare_ns",
    "assembly_ns", "output_compare_ns", "close_ns",
}
TRACE_KEYS = {
    "case_id", "input_dtype", "poison", "native", "bridge_status", "hidden_words",
    "bridge_bytes", "bridge_words", "output_words", "bridge_checked_words",
    "bridge_mismatches", "output_checked_words", "output_mismatches", "resources",
    "owner_cleanup", "result",
} | TRACE_FLAGS | TRACE_TIMES
STAGE_FLAGS = {"submitted", "waited", "trace_valid", "output_valid", "compared", "closed"}
STAGE_TIMES = {"submit_begin_ns", "submit_end_ns", "wait_ns", "compare_ns", "close_ns"}
STAGE_KEYS = {
    "operation_id", "sequence", "row_begin", "row_end", "submission", "completion",
    "cleanup", "dispatch", "a_size", "b_size", "output_count", "a_bytes", "b_bytes",
    "output_words", "checked_words", "mismatches",
} | STAGE_FLAGS | STAGE_TIMES
DISPATCH_NUMBERS = {
    "m", "n", "k", "poison", "a_address", "b_address", "d_address", "a_bytes",
    "b_bytes", "d_bytes", "writes_enqueued", "launches_enqueued", "reads_enqueued",
    "wait_calls", "timed_out_waits",
}
DISPATCH_KEYS = {
    "qualification_id", "input_dtype", "argument_bytes", "event_results",
    "profiling_enabled", "event_profiles", "event_profile_results", "event_profile_queried",
} | DISPATCH_NUMBERS
PROFILE_KEYS = {"queued_ns", "submit_ns", "start_ns", "end_ns"}
RESOURCE_KEYS = {
    "before_valid", "after_valid", "before_status", "after_status", "free_before",
    "used_before", "free_after", "used_after",
}
OPERATIONS = (
    ("hidden_matmul", (16, 8, 16), (0, 16)),
    ("output_rows_0_7", (8, 4, 8), (0, 8)),
    ("output_rows_8_15", (8, 4, 8), (8, 16)),
)


def _object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "duplicate model result field: " + key)
        value[key] = item
    return value


def _noninteger(token):
    raise ValueError("model result contains a noninteger number: " + token[:32])


def _fields(value, expected, label):
    require(type(value) is dict and set(value) == expected, "incorrect " + label + " fields")


def _uint(value, label):
    require(type(value) is int and 0 <= value <= UINT64_MAX, "invalid integer: " + label)
    return value


def _true(value, label):
    require(type(value) is bool and value, "missing successful observation: " + label)


def _equal_uint(value, expected, label):
    require(_uint(value, label) == expected, "incorrect " + label)


def _words(value, count, label):
    require(type(value) is list and len(value) == count
            and all(type(word) is str and WORD.fullmatch(word) for word in value),
            "invalid word array: " + label)
    return value


def _bytes(value, count, label):
    require(type(value) is str and len(value) == count * 2
            and re.fullmatch(r"[0-9a-f]*", value), "invalid byte array: " + label)
    return bytes.fromhex(value)


def _packed(words):
    return b"".join(int(word, 16).to_bytes(4, "little") for word in words)


def _execution(value, label, *, complete=True):
    _fields(value, EXECUTION_KEYS, label)
    for key in ("validation", "primary", "cleanup"):
        _equal_uint(value[key], 0, label + "." + key)
    require(type(value["complete"]) is bool, "invalid completion flag: " + label)
    if complete:
        _true(value["complete"], label + ".complete")


def _case(case):
    required = {"id", "format", "input_words", "w1_words", "w2_words", "hidden_words",
                "bridge_words", "output_words"}
    require(type(case) is dict and required <= set(case), "incomplete trusted model case")
    require(type(case["id"]) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", case["id"]),
            "invalid trusted model case ID")
    require(case["format"] in ("fp16", "bf16"), "unsupported trusted model format")
    for key, count in (("input_words", 128), ("w1_words", 64), ("w2_words", 16),
                       ("hidden_words", 128), ("bridge_words", 64), ("output_words", 64)):
        _words(case[key], count, "trusted " + key)


def _profiles(dispatch, stage):
    _true(dispatch["profiling_enabled"], "profiling enabled")
    for name in ("event_results", "event_profile_results", "event_profile_queried", "event_profiles"):
        require(type(dispatch[name]) is list and len(dispatch[name]) == 5,
                "incorrect five-event observation inventory: " + name)
    previous_end = 0
    for index, profile in enumerate(dispatch["event_profiles"]):
        _equal_uint(dispatch["event_results"][index], 0, "event result")
        _true(dispatch["event_profile_queried"][index], "profile query")
        _equal_uint(dispatch["event_profile_results"][index], 0, "profile query result")
        _fields(profile, PROFILE_KEYS, "event profile")
        for key in PROFILE_KEYS:
            _uint(profile[key], key)
        queued, submitted, started, ended = (profile[key] for key in
                                            ("queued_ns", "submit_ns", "start_ns", "end_ns"))
        require(queued <= submitted <= started <= ended, "event timestamps are out of order")
        require(stage["submit_begin_ns"] <= queued <= stage["submit_end_ns"],
                "event enqueue is outside its actual submission")
        require(previous_end <= submitted, "dependent event started before predecessor completed")
        previous_end = ended
    return previous_end


def _dispatch(dispatch, stage, *, shape, fmt, poison, binding_id):
    _fields(dispatch, DISPATCH_KEYS, "native dispatch")
    for key in DISPATCH_NUMBERS:
        _uint(dispatch[key], "dispatch." + key)
    require(dispatch["qualification_id"] == binding_id and dispatch["input_dtype"] == fmt,
            "native dispatch binding/format differs")
    m, n, k = shape
    require(tuple(dispatch[key] for key in ("m", "n", "k")) == shape, "native dispatch shape differs")
    _equal_uint(dispatch["poison"], poison, "native poison")
    sizes = (m * k * 2, k * n * 2, m * n * 4)
    require(tuple(dispatch[key] for key in ("a_bytes", "b_bytes", "d_bytes")) == sizes,
            "native tensor transfer extents differ")
    require(tuple(dispatch[key] for key in ("writes_enqueued", "launches_enqueued", "reads_enqueued"))
            == (3, 1, 1), "native transfer/launch inventory differs")
    require(dispatch["wait_calls"] > dispatch["timed_out_waits"],
            "no observed successful completion wait")
    addresses = tuple(dispatch[key] for key in ("a_address", "b_address", "d_address"))
    ranges = []
    for address, size in zip(addresses, sizes):
        require(address % 4 == 0 and address <= (1 << 64) - size,
                "invalid aligned native allocation range")
        ranges.append((address, address + size))
    require(all(left[1] <= right[0] or right[1] <= left[0]
                for index, left in enumerate(ranges) for right in ranges[index + 1:]),
            "native operand allocations overlap")
    wire = _bytes(dispatch["argument_bytes"], 56, "native argument bytes")
    expected = struct.pack("<8I3Q", 1, 56, 1 if fmt == "fp16" else 2, 0, m, n, k, 0, *addresses)
    require(wire == expected, "native argument bytes differ from the validated shape/addresses")
    return _profiles(dispatch, stage)


def _trace(trace, case, iteration, binding_id):
    _fields(trace, TRACE_KEYS, "model trace")
    require(trace["case_id"] == case["id"] and trace["input_dtype"] == case["format"],
            "model trace identity differs")
    poison = (0x7FC0DEAD, 0xDEADBEEF)[iteration]
    _equal_uint(trace["poison"], poison, "model poison")
    for key in TRACE_FLAGS:
        _true(trace[key], key)
    for key in TRACE_TIMES:
        _uint(trace[key], key)
    require(trace["create_begin_ns"] <= trace["create_end_ns"], "model creation timestamps are reversed")
    _equal_uint(trace["bridge_status"], 0, "host bridge status")
    for key, expected in (("bridge_checked_words", 64), ("bridge_mismatches", 0),
                          ("output_checked_words", 64), ("output_mismatches", 0)):
        _equal_uint(trace[key], expected, key)
    for key, count in (("hidden_words", 128), ("bridge_words", 64), ("output_words", 64)):
        require(_words(trace[key], count, key) == case[key], "actual " + key + " differ from frozen reference")
    bridge = _bytes(trace["bridge_bytes"], 256, "actual bridge")
    require(bridge == _packed(trace["bridge_words"]), "actual bridge bytes/words disagree")
    resources = trace["resources"]
    _fields(resources, RESOURCE_KEYS, "model resources")
    for key in ("before_valid", "after_valid"):
        _true(resources[key], key)
    for key in ("before_status", "after_status"):
        _equal_uint(resources[key], 0, key)
    for key in ("free_before", "used_before", "free_after", "used_after"):
        _uint(resources[key], key)
    require(resources["free_before"] == resources["free_after"]
            and resources["used_before"] == resources["used_after"], "model resources were not restored")
    _execution(trace["owner_cleanup"], "owner cleanup")
    model_result = trace["result"]
    _fields(model_result, MODEL_RESULT_KEYS, "model result")
    require(model_result["status"] == "success", "model inference did not succeed")
    _true(model_result["terminal"], "model terminal")
    _execution(model_result["execution"], "model execution")
    require(type(trace["native"]) is list and len(trace["native"]) == 3, "expected exactly three native stages")
    previous_end = trace["create_end_ns"]
    outputs = []
    for index, (stage, (identifier, shape, rows)) in enumerate(zip(trace["native"], OPERATIONS)):
        _fields(stage, STAGE_KEYS, "native stage")
        require(stage["operation_id"] == identifier, "native graph operation is reordered or missing")
        for key, expected in (("sequence", index), ("row_begin", rows[0]), ("row_end", rows[1]),
                              ("a_size", shape[0] * shape[2] * 2),
                              ("b_size", shape[1] * shape[2] * 2),
                              ("output_count", shape[0] * shape[1]),
                              ("checked_words", shape[0] * shape[1]), ("mismatches", 0)):
            _equal_uint(stage[key], expected, "stage." + key)
        for key in STAGE_FLAGS:
            _true(stage[key], "stage." + key)
        for key in STAGE_TIMES:
            _uint(stage[key], "stage." + key)
        require(previous_end <= stage["submit_begin_ns"] <= stage["submit_end_ns"],
                "native stage submission precedes its dependency")
        _execution(stage["submission"], "native submission", complete=False)
        _execution(stage["completion"], "native completion")
        _execution(stage["cleanup"], "native cleanup")
        expected_a = _packed(case["input_words"]) if index == 0 else bridge[(index - 1) * 128:index * 128]
        expected_b = _packed(case["w1_words"] if index == 0 else case["w2_words"])
        require(_bytes(stage["a_bytes"], stage["a_size"], "actual A") == expected_a,
                "actual native A bytes break the model data lineage")
        require(_bytes(stage["b_bytes"], stage["b_size"], "actual B") == expected_b,
                "actual native B bytes differ from frozen weights")
        expected_output = trace["hidden_words"] if index == 0 else case["output_words"][(index - 1) * 32:index * 32]
        actual = _words(stage["output_words"], stage["output_count"], "native actual output")
        require(actual == expected_output, "native actual output block differs")
        if index:
            outputs.extend(actual)
        previous_end = _dispatch(stage["dispatch"], stage, shape=shape, fmt=case["format"],
                                 poison=poison, binding_id=binding_id)
    require(outputs == trace["output_words"], "assembled output differs from actual native row blocks")


def verify_output(text, case, iterations, binding_id, *, backend, source_revision, fixture_sha256):
    require(type(text) is str and len(text) <= MAX_LOG_BYTES, "model log is missing or oversized")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeError as error:
        raise ValueError("model log is not valid UTF-8") from error
    require(size <= MAX_LOG_BYTES, "model log exceeds its byte bound")
    require(type(iterations) is int and iterations in (1, 2), "invalid model repetition count")
    for value, pattern, label in ((binding_id, SHA256, "execution binding"),
                                  (fixture_sha256, SHA256, "fixture digest"),
                                  (source_revision, COMMIT, "source revision")):
        require(type(value) is str and pattern.fullmatch(value), "invalid " + label)
    require(type(backend) is str and backend in ("simx", "rtlsim"), "unsupported execution backend")
    _case(case)
    require(not any((ord(char) < 32 and char not in "\t\n\r") or 127 <= ord(char) <= 159 for char in text),
            "model log contains control bytes")
    require(not re.search(r"\b(?:FAILED|FAIL|ERROR|FATAL|ABORTED|MISMATCH)\b|"
                          r"P04_FAILURE|Segmentation fault|runtime error:", text, re.IGNORECASE),
            "model log contains a failure")
    lines = text.splitlines()
    require(lines and lines[-1] == "PASSED!" and lines.count("PASSED!") == 1
            and len(re.findall(r"\bPASSED\b", text, re.IGNORECASE)) == 1,
            "missing or ambiguous final success record")
    results = []
    for line in lines:
        if not re.search("P04_RESULT", line, re.IGNORECASE):
            continue
        require(line.startswith("P04_RESULT "), "malformed model result marker")
        payload = line[len("P04_RESULT "):]
        require(len(payload.encode("utf-8")) <= MAX_RECORD_BYTES, "model record exceeds its byte bound")
        try:
            row = json.loads(payload, object_pairs_hook=_object,
                             parse_constant=_noninteger, parse_float=_noninteger)
        except (RecursionError, OverflowError) as error:
            raise ValueError("model result exceeds JSON parser bounds") from error
        _fields(row, RESULT_KEYS, "model result record")
        _equal_uint(row["schema_version"], 1, "model record schema version")
        _equal_uint(row["iteration"], len(results), "model repetition order")
        require(len(results) < iterations, "extra model repetition")
        for key, expected in (("model_id", "p04-tiny-mlp-v1"),
                              ("fixture_id", "p04-tiny-mlp-fixture-v1"),
                              ("fixture_sha256", fixture_sha256), ("source_revision", source_revision),
                              ("backend", backend), ("qualification_id", binding_id),
                              ("clock", "std::chrono::steady_clock"),
                              ("timing_scope", "host_runtime_observations")):
            require(type(row[key]) is str and row[key] == expected, "model record " + key + " differs")
        _trace(row["trace"], case, len(results), binding_id)
        if results:
            previous_end = results[-1]["trace"]["native"][-1]["dispatch"]["event_profiles"][-1]["end_ns"]
            require(previous_end <= row["trace"]["create_begin_ns"],
                    "model repetition precedes its completed predecessor")
        results.append(row)
    require(len(results) == iterations, "missing model repetition")
    return results
