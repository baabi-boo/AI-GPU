# SPDX-License-Identifier: Apache-2.0
"""Independently reconcile inert strict-governance discovery and event records."""

from __future__ import annotations

import hashlib
import io
import json
import math
import re


SCOPE = "project-governance-unittest-only"
DISCOVERY = {"start_directory": "ci/project", "pattern": "test_*.py"}
MAX_TESTS = 100_000
MAX_ID_BYTES = 4096
MAX_RECORD_BYTES = 32 * 1024**2
MAX_EVENTS = 1_000_000
MAX_EVENT_LINE_BYTES = 64 * 1024
_BASE_EVENT_KEYS = {"sequence", "event", "elapsed_seconds", "test_id"}
_HASH_LABEL_KEYS = {
    "subtest_id_encoding", "subtest_id_original_encoding", "subtest_id_original_bytes",
}
_DISCREPANCIES = (
    "duplicate_discovered_ids", "missing_started_ids", "unexpected_started_ids",
    "duplicate_started_ids", "missing_stopped_ids", "unexpected_stopped_ids",
    "duplicate_stopped_ids", "missing_outcome_ids", "unexpected_outcome_ids",
    "duplicate_outcome_ids",
)


class ReplayEventsError(ValueError):
    """The retained event evidence does not establish strict successful coverage."""


def _require(condition, message):
    if not condition:
        raise ReplayEventsError(message)


def _keys(record, expected, label):
    _require(type(record) is dict and set(record) == set(expected),
             label + " has missing, unexpected, or malformed fields")


def _equal(actual, expected, label):
    _require(type(actual) is type(expected), label + " has an invalid type")
    if type(expected) is dict:
        _keys(actual, expected, label)
        for key, value in expected.items():
            _equal(actual[key], value, label + "." + key)
    else:
        _require(actual == expected, label + " does not match replayed evidence")


def _identity(value, label):
    _require(type(value) is str and bool(value), label + " must be a nonempty identity")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ReplayEventsError(label + " is not valid UTF-8") from exc
    _require(size <= MAX_ID_BYTES, label + " exceeds the identity byte limit")


def _clock(value, label):
    _require(type(value) in (int, float), label + " must be a finite nonnegative number")
    try:
        valid = math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    _require(valid, label + " must be a finite nonnegative number")
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "event JSON contains a duplicate object key")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ReplayEventsError("event JSON contains a nonfinite number")


def _event_records(events):
    _require(type(events) is bytes, "events must be retained bytes")
    _require(0 < len(events) <= MAX_RECORD_BYTES, "event evidence is empty or exceeds the byte limit")
    _require(events.endswith(b"\n"), "event evidence has a truncated final line")
    stream = io.BytesIO(events)
    number = 0
    while True:
        line = stream.readline(MAX_EVENT_LINE_BYTES + 1)
        if not line:
            return
        number += 1
        label = "events line " + str(number)
        _require(number <= MAX_EVENTS, "event evidence exceeds the event count limit")
        _require(len(line) <= MAX_EVENT_LINE_BYTES and line.endswith(b"\n"),
                 label + " exceeds the line byte limit")
        try:
            record = json.loads(line.decode("utf-8"), object_pairs_hook=_unique_object,
                                parse_constant=_invalid_constant)
        except ReplayEventsError as exc:
            raise ReplayEventsError(label + ": " + str(exc)) from exc
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise ReplayEventsError(label + " is malformed JSON") from exc
        _require(type(record) is dict, label + " must be a JSON object")
        yield number, record


def _subtest(record, parent, label):
    hashed = bool(_HASH_LABEL_KEYS.intersection(record))
    fields = _BASE_EVENT_KEYS | {"outcome", "subtest_id"}
    _keys(record, fields | (_HASH_LABEL_KEYS if hashed else set()), label)
    identity = record["subtest_id"]
    _identity(identity, label + ".subtest_id")
    if hashed:
        _require(re.fullmatch(r"sha256:[0-9a-f]{64}", identity) is not None,
                 label + " has an invalid hash-bound subtest identity")
        _equal(record["subtest_id_encoding"], "sha256", label + ".subtest_id_encoding")
        _equal(record["subtest_id_original_encoding"], "utf-8",
               label + ".subtest_id_original_encoding")
        size = record["subtest_id_original_bytes"]
        _require(type(size) is int and size > MAX_ID_BYTES,
                 label + " has an invalid original subtest byte length")
    else:
        prefix = parent + " "
        _require(identity.startswith(prefix) and len(identity) > len(prefix),
                 label + " has a subtest identity belonging to a different parent")


def reconcile(discovered: dict, events: bytes, execution: dict) -> dict:
    """Return checked execution statistics; callers must strictly decode both JSON objects."""
    _keys(discovered, {"schema_version", "scope", "discovery", "test_ids", "count", "sha256"},
          "discovered")
    _equal(discovered["schema_version"], 1, "discovered.schema_version")
    _equal(discovered["scope"], SCOPE, "discovered.scope")
    _equal(discovered["discovery"], DISCOVERY, "discovered.discovery")
    identities = discovered["test_ids"]
    _require(type(identities) is list and 0 < len(identities) <= MAX_TESTS,
             "discovered.test_ids must be a nonempty bounded list")
    digest = hashlib.sha256()
    unique = set()
    for identity in identities:
        _identity(identity, "discovered.test_ids entry")
        _require(identity not in unique, "discovered.test_ids contains a duplicate identity")
        _require(not identity.startswith("unittest.loader._FailedTest."),
                 "discovered.test_ids contains a unittest loader failure")
        unique.add(identity)
        digest.update((identity + "\n").encode("utf-8"))
    count = len(identities)
    digest = digest.hexdigest()
    _equal(discovered["count"], count, "discovered.count")
    _equal(discovered["sha256"], digest, "discovered.sha256")

    active = None
    successful = False
    started = stopped = outcomes = subtests = event_count = 0
    previous_time = 0
    for number, record in _event_records(events):
        label = "events line " + str(number)
        event = record.get("event")
        _require(type(event) is str and event in {
            "test_start", "test_outcome", "test_stop", "subtest_outcome",
        }, label + " contains a fixture outcome or unknown event")
        if event == "subtest_outcome":
            _require(active is not None and not successful,
                     label + " has a subtest outside its parent's active body")
            _subtest(record, active, label)
        else:
            _keys(record, _BASE_EVENT_KEYS | ({"outcome"} if event == "test_outcome" else set()),
                  label)
        _equal(record["sequence"], number, label + ".sequence")
        elapsed = _clock(record["elapsed_seconds"], label + ".elapsed_seconds")
        _require(elapsed >= previous_time, label + " has a decreasing event clock")
        previous_time = elapsed
        identity = record["test_id"]
        _identity(identity, label + ".test_id")
        if event == "test_start":
            _require(active is None, label + " starts a test while another test is active")
            _require(started < count and identity == identities[started],
                     label + " does not follow the discovered test order")
            active = identity
            successful = False
            started += 1
        else:
            _require(active is not None and identity == active,
                     label + " does not belong to the active test")
            if event == "test_stop":
                _require(successful, label + " stops a test without one successful outcome")
                stopped += 1
                active = None
            else:
                _require(not successful, label + " follows an already completed test outcome")
                _equal(record["outcome"], "success", label + ".outcome")
                if event == "test_outcome":
                    outcomes += 1
                    successful = True
                else:
                    subtests += 1
        event_count = number
    _require(active is None and started == stopped == outcomes == count,
             "event evidence does not finish the complete discovered population")

    _require(type(execution) is dict, "execution must be a JSON object")
    duration = _clock(execution.get("duration_seconds"), "execution.duration_seconds")
    _require(duration >= previous_time, "execution duration precedes the final event clock")
    derived = {
        "schema_version": 1, "scope": SCOPE, "strict_success": True,
        "execution_completed": True, "coverage_complete": True,
        "order_matches": True, "counts_match": True, "discovered_count": count,
        "discovered_sha256": digest, "tests_run": started, "started_count": started,
        "stopped_count": stopped, "outcome_counts": {"success": outcomes},
        "fixture_counts": {}, "subtest_counts": {"success": subtests} if subtests else {},
        "non_successful_ids": [], "loader_errors": [], "abort": None,
        "event_count": event_count, "duration_seconds": duration,
        **{name: [] for name in _DISCREPANCIES},
    }
    _equal(execution, derived, "execution")
    return derived
