# SPDX-License-Identifier: Apache-2.0
"""Validate native public diagnostic observations as bounded inert data.

Consistency does not authenticate execution. Source/build/process provenance is
checked separately, and these diagnostics never qualify a warm measurement.
"""

from __future__ import annotations

import json
import re


MODES = ("normal", "immediate-overflow", "delayed-overflow", "cache-overflow", "coherent-terminal")
RESULT_PREFIX = "COUNTER_PUBLIC_RESULT "
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_RESULT_BYTES = 256 * 1024
MAX_UINT64 = (1 << 64) - 1
MAX_UINT32 = (1 << 32) - 1
SENTINEL = 0xDECAFBAD12345678
SEED_BASE = 0x1234567800000000
MPM_BASE = 0xB00
MPM_DCR = 1
INVALID_VALUE = 3

# The fixed transport inventory is independent of the producer's reported rows.
SELECTORS = (
    ("cycles", 0, 2816, 1), ("instructions", 0, 2818, 1),
    ("core_sched_idle", 1, 2819, 1), ("core_active_warps", 1, 2820, 1),
    ("core_stalled_warps", 1, 2821, 1), ("core_issued_warps", 1, 2822, 1),
    ("core_issued_threads", 1, 2823, 1), ("core_stall_scrb", 1, 2826, 1),
    ("core_stall_lsu", 1, 2830, 1), ("core_stall_tcu", 1, 2832, 1),
    ("core_instr_tcu", 1, 2839, 1), ("core_loads", 1, 2844, 1),
    ("core_stores", 1, 2846, 1), ("icache_reads", 3, 2819, 1),
    ("icache_miss_r", 3, 2820, 1), ("icache_mshr_st", 3, 2821, 1),
    ("dcache_reads", 4, 2819, 2), ("dcache_writes", 4, 2820, 2),
    ("dcache_miss_r", 4, 2821, 2), ("dcache_miss_w", 4, 2822, 2),
    ("dcache_evicts", 4, 2823, 2), ("dcache_mshr_st", 4, 2825, 2),
    ("lmem_reads", 7, 2823, 1), ("lmem_writes", 7, 2824, 1),
    ("lmem_bank_st", 7, 2825, 1), ("coalescer_miss", 7, 2826, 1),
    ("memory_reads", 7, 2819, 1), ("memory_writes", 7, 2820, 1),
    ("memory_lt", 7, 2821, 1), ("memory_bank_st", 7, 2822, 1),
    ("tcu_tbuf_stalls", 11, 2819, 1), ("tcu_tbuf_cache_hits", 11, 2820, 1),
    ("tcu_lmem_reads", 11, 2821, 2),
)

# Derived from the fixed harness control flow, not a native execution receipt.
CHECKS = {"normal": 1652, "coherent-terminal": 1798,
          "immediate-overflow": 1168, "delayed-overflow": 1168, "cache-overflow": 1165}
PROGRAM_WORDS = [0x00700193, 0x0000700B, 0x0000000B]
MODEL_FIELDS = {"live", "inventory_ready", "idle", "any_running", "generation", "ticks",
                "reset_generation", "pending_reads", "core_cycles", "core_instructions",
                "exitcode", "components"}
READ_FIELDS = {"sequence", "generation", "addr", "tag", "value", "status", "completed",
               "overflow", "ticks_before", "ticks_after", "reset_before", "reset_after",
               "class_before", "class_after"}
CP_FIELDS = {"control", "queue_control", "status", "error", "retired", "expected", "head", "tail"}
TERMINAL_FIELDS = {"seeded", "selectors", "components", "unavailable_unqueried", "device_refs",
                   "queues", "buffers", "extra_retain_rejected", "witness", "before", "after",
                   "cp_before", "cp_after", "rows"}
RESULT_FIELDS = {"schema_version", "mode", "backend", "memory_route", "xlen", "checked",
                 "native_model", "public_runtime", "checks", "failures", "constructed", "destroyed",
                 "run_entries", "run_completed", "run_errors", "dcr_read_entries", "dcr_read_completed",
                 "dcr_read_errors", "dcr_write_entries", "dcr_write_completed", "overflow_errors",
                 "unexpected_errors", "violations", "fresh_context_success", "program_words_verified",
                 "terminal_failure", "suppressed_requests", "failure", "terminal_snapshots",
                 "destructions", "qualified", "ready_for_warm", "warm_execution", "acceptance_claimed"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _fields(value, names, label):
    require(type(value) is dict and set(value) == set(names), label + ": missing or unknown fields")


def _fixed(actual, expected, label):
    require(type(actual) is type(expected) and actual == expected, label + ": value or type differs")


def _integer(value, low, high, label):
    require(type(value) is int and low <= value <= high, label + ": integer is outside its bound")


def _uint(value, label, *, bits=64, minimum=0):
    _integer(value, minimum, (1 << bits) - 1, label)


def _array(value, size, label):
    require(type(value) is list and len(value) == size, label + ": inventory length differs")


def _model(value, generation, label, *, healthy=False, reset=None):
    _fields(value, MODEL_FIELDS, label)
    for name in ("live", "inventory_ready"):
        _fixed(value[name], True, label + "." + name)
    for name in ("idle", "any_running"):
        require(type(value[name]) is bool, label + "." + name + ": expected a boolean")
    for name in ("generation", "ticks", "reset_generation", "pending_reads", "core_cycles", "core_instructions"):
        _uint(value[name], label + "." + name)
    _fixed(value["generation"], generation, label + ".generation")
    if reset is not None:
        _fixed(value["reset_generation"], reset, label + ".reset_generation")
    _integer(value["exitcode"], -(1 << 31), (1 << 31) - 1, label + ".exitcode")
    _array(value["components"], 40, label + ".components")
    for index, item in enumerate(value["components"]):
        _uint(item, label + ".components[" + str(index) + "]")
    require(value["components"][:2] == [value["core_cycles"], value["core_instructions"]],
            label + ": core observations differ from actual backing components")
    if healthy:
        require(value["idle"] and not value["any_running"] and value["pending_reads"] == 0,
                label + ": successful model is not quiescent")
        require(value["exitcode"] == 7 and value["core_cycles"] > 0 and value["core_instructions"] > 0
                and value["ticks"] > 0, label + ": successful native scalar witness is absent")


def _read(value, selector, state, sequence, high, label, *, failed=False):
    _fields(value, READ_FIELDS, label)
    name, perf_class, csr, _ = selector
    expected = {"sequence": sequence, "generation": state["generation"], "addr": MPM_DCR,
                "tag": (perf_class << 22) | ((csr - MPM_BASE + (32 if high else 0)) << 16),
                "status": -1 if failed else 0, "completed": not failed, "overflow": failed,
                "ticks_before": state["ticks"], "ticks_after": state["ticks"],
                "reset_before": state["reset_generation"], "reset_after": state["reset_generation"],
                "class_before": 0, "class_after": perf_class if failed else 0}
    for key, item in expected.items():
        _fixed(value[key], item, label + "." + key)
    _uint(value["value"], label + ".value", bits=32)
    if failed:
        _fixed(value["value"], 0, label + ".value")


def _cp(value, label):
    _fields(value, CP_FIELDS, label)
    for name, item in (("control", 1), ("queue_control", 1), ("status", 0), ("error", 0)):
        _fixed(value[name], item, label + "." + name)
    for name in ("retired", "expected"):
        _uint(value[name], label + "." + name, bits=32, minimum=22)
    for name in ("head", "tail"):
        _uint(value[name], label + "." + name, minimum=64)
    require(value["retired"] == value["expected"] and value["head"] == value["tail"]
            and value["tail"] == 64 * value["expected"], label + ": CP work is not fully retired")


def _terminal(value, generation, seeded, first_sequence, label):
    _fields(value, TERMINAL_FIELDS, label)
    fixed = {"seeded": seeded, "selectors": 33, "components": 40, "unavailable_unqueried": 12,
             "device_refs": 1, "queues": 0, "buffers": 0, "extra_retain_rejected": True}
    for key, item in fixed.items():
        _fixed(value[key], item, label + "." + key)
    for key in ("witness", "before", "after"):
        _model(value[key], generation, label + "." + key, healthy=True, reset=2 * generation)
    require(value["before"] == value["after"], label + ": model changed during terminal readout")
    if seeded:
        seeded_components = [SEED_BASE + 2 * index + component
                             for index, selected in enumerate(SELECTORS)
                             for component in range(selected[3])]
        require(value["before"]["components"] == seeded_components, label + ": coherent seeds differ")
        for key in MODEL_FIELDS - {"components", "core_cycles", "core_instructions"}:
            require(value["witness"][key] == value["before"][key],
                    label + ": model lifecycle changed during diagnostic seeding")
    else:
        require(value["witness"] == value["before"], label + ": unseeded model changed during resource release")
    for key in ("cp_before", "cp_after"):
        _cp(value[key], label + "." + key)
    require(value["cp_after"]["expected"] == value["cp_before"]["expected"] + 66,
            label + ": terminal reads did not retire exactly 66 CP commands")
    _array(value["rows"], len(SELECTORS), label + ".rows")
    offset = 0
    for index, (row, selected) in enumerate(zip(value["rows"], SELECTORS)):
        row_label = label + ".rows[" + str(index) + "]"
        _fields(row, {"name", "class", "csr", "components", "value", "low", "high"}, row_label)
        for key, item in zip(("name", "class", "csr", "components"), selected):
            _fixed(row[key], item, row_label + "." + key)
        count = selected[3]
        total = sum(value["before"]["components"][offset:offset + count])
        require(total <= MAX_UINT64, row_label + ": backing aggregate overflows uint64")
        _fixed(row["value"], total, row_label + ".value")
        for high, key in ((False, "low"), (True, "high")):
            _read(row[key], selected, value["before"], first_sequence + 2 * index + int(high),
                  high, row_label + "." + key)
            _fixed(row[key]["value"], (total >> (32 if high else 0)) & MAX_UINT32,
                   row_label + "." + key + ".value")
        require(row["value"] == (row["high"]["value"] << 32) | row["low"]["value"],
                row_label + ": public value does not reconstruct both native replies")
        offset += count
    require(offset == 40, label + ": backing inventory differs")


def _query(value, selector, label):
    _fields(value, {"class", "csr", "status", "before", "after"}, label)
    for key, item in {"class": selector[1], "csr": selector[2], "status": INVALID_VALUE,
                      "before": SENTINEL, "after": SENTINEL}.items():
        _fixed(value[key], item, label + "." + key)


def _failure(value, mode):
    label = "failure"
    _fields(value, {"asynchronous", "seed", "before", "after", "trigger_query", "suppression", "reads"}, label)
    asynchronous = mode != "cache-overflow"
    _fixed(value["asynchronous"], asynchronous, label + ".asynchronous")
    seed = MAX_UINT64 - (2 if mode == "delayed-overflow" else 0)
    _fixed(value["seed"], seed, label + ".seed")
    before, after = value["before"], value["after"]
    _model(before, 1, "failure.before", healthy=not asynchronous, reset=1 if asynchronous else 2)
    _model(after, 1, "failure.after", healthy=not asynchronous, reset=2)
    if asynchronous:
        require(before["idle"] and not before["any_running"] and before["pending_reads"] == 0,
                "failure: native seed was not quiescent")
        require(before["components"] == [seed] + [0] * 39 and before["ticks"] == 0
                and before["exitcode"] == 0, "failure: native updater did not start from its fresh seeded state")
        require(after["core_cycles"] == MAX_UINT64 and after["core_instructions"] == 0
                and after["exitcode"] == 0, "failure: updater wrapped or retired the scalar program")
        require(all(new >= old for old, new in zip(before["components"], after["components"])),
                "failure: an actual cumulative component decreased")
        if mode == "delayed-overflow":
            require(after["core_cycles"] - before["core_cycles"] == 2 and after["ticks"] > 0,
                    "failure: delayed native updater made no observed progress")
        _fixed(value["trigger_query"], None, "failure.trigger_query")
        _array(value["reads"], 0, "failure.reads")
    else:
        require(before == after and before["components"][16:18] == [MAX_UINT64, 1],
                "failure: actual cache aggregate sources changed or were not poisoned")
        _query(value["trigger_query"], SELECTORS[16], "failure.trigger_query")
        _array(value["reads"], 1, "failure.reads")
        _read(value["reads"][0], SELECTORS[16], before, 1, False, "failure.reads[0]", failed=True)
    suppression = value["suppression"]
    _fields(suppression, {"before_entries", "after_entries", "queries", "dma"}, "failure.suppression")
    expected = {"run": 1, "read": int(not asynchronous), "write": 19, "overflows": 1}
    for key in ("before_entries", "after_entries"):
        _fields(suppression[key], expected, "failure.suppression." + key)
        for field, item in expected.items():
            _fixed(suppression[key][field], item, "failure.suppression." + key + "." + field)
    _array(suppression["queries"], 2, "failure.suppression.queries")
    for index, query in enumerate(suppression["queries"]):
        _query(query, SELECTORS[0], "failure.suppression.queries[" + str(index) + "]")
    dma = suppression["dma"]
    _fields(dma, {"address", "status", "before", "attempted", "after"}, "failure.suppression.dma")
    _integer(dma["address"], 0, MAX_UINT64 - 12, "failure.suppression.dma.address")
    _fixed(dma["status"], 3, "failure.suppression.dma.status")
    for name, expected_words in (("before", PROGRAM_WORDS), ("after", PROGRAM_WORDS),
                                 ("attempted", [word ^ 0xFFFFFFFF for word in PROGRAM_WORDS])):
        _array(dma[name], 3, "failure.suppression.dma." + name)
        for index, word in enumerate(dma[name]):
            _uint(word, "failure.suppression.dma." + name + "[" + str(index) + "]", bits=32)
        _fixed(dma[name], expected_words, "failure.suppression.dma." + name)


def _destruction(value, expected, label):
    _fields(value, {"before", "completed", "ticks_after", "reset_after", "idle_after"}, label)
    _model(value["before"], expected["generation"], label + ".before", reset=expected["reset_generation"])
    require(value["before"] == expected, label + ": actual destruction boundary differs from final observation")
    for key, item in {"completed": True, "ticks_after": 0, "reset_after": expected["reset_generation"],
                      "idle_after": True}.items():
        _fixed(value[key], item, label + "." + key)


def verify_record(value, mode):
    """Recompute a decoded record without opening producer paths or files."""
    require(type(mode) is str and mode in MODES, "unknown public diagnostic mode")
    _fields(value, RESULT_FIELDS, "result")
    negative = mode in ("immediate-overflow", "delayed-overflow", "cache-overflow")
    asynchronous = mode in ("immediate-overflow", "delayed-overflow")
    read_errors = int(mode == "cache-overflow")
    reads = (66 if negative else 132) + read_errors
    fixed = {"schema_version": 1, "mode": mode, "backend": "simx", "memory_route": "direct-ram",
             "xlen": 64, "checked": True, "native_model": True, "public_runtime": True,
             "checks": CHECKS[mode], "failures": 0, "constructed": 2, "destroyed": 2,
             "run_entries": 2, "run_completed": 1 if asynchronous else 2,
             "run_errors": int(asynchronous), "dcr_read_entries": reads,
             "dcr_read_completed": reads - read_errors, "dcr_read_errors": read_errors,
             "dcr_write_entries": 38, "dcr_write_completed": 38, "overflow_errors": int(negative),
             "unexpected_errors": 0, "violations": 0, "fresh_context_success": True,
             "program_words_verified": 6, "terminal_failure": negative,
             "suppressed_requests": 5 if negative else 0, "qualified": False, "ready_for_warm": False,
             "warm_execution": False, "acceptance_claimed": False}
    for key, item in fixed.items():
        _fixed(value[key], item, "result." + key)
    terminals = value["terminal_snapshots"]
    _array(terminals, 1 if negative else 2, "terminal_snapshots")
    if negative:
        _failure(value["failure"], mode)
        _terminal(terminals[0], 2, False, 1 + read_errors, "terminal_snapshots[0]")
        final_states = (value["failure"]["after"], terminals[0]["after"])
    else:
        _fixed(value["failure"], None, "failure")
        for index, terminal in enumerate(terminals):
            _terminal(terminal, index + 1, mode == "coherent-terminal" and index == 0,
                      1 + 66 * index, "terminal_snapshots[" + str(index) + "]")
        final_states = tuple(terminal["after"] for terminal in terminals)
    _array(value["destructions"], 2, "destructions")
    for index, (destroyed, final_state) in enumerate(zip(value["destructions"], final_states)):
        _destruction(destroyed, final_state, "destructions[" + str(index) + "]")
    return value


def _json_depth(text):
    depth, quoted, escaped = 0, False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            require(depth <= 16, "public result nesting exceeds its bound")
        elif char in "]}":
            depth -= 1
            require(depth >= 0, "public result has invalid nesting")


def verify_output(text, mode):
    """Parse one bounded result line and independently validate its observations."""
    require(type(text) is str and len(text.encode("utf-8")) <= MAX_OUTPUT_BYTES,
            "public output is not bounded text")
    require(not any((ord(char) < 32 and char not in "\t\n") or 127 <= ord(char) <= 159
                    or (char.isspace() and char not in " \t\n") for char in text),
            "public output contains unsupported record separators")
    lines = [line for line in text.split("\n") if line.strip()]
    selected = [line for line in lines if line.startswith(RESULT_PREFIX)]
    require(len(selected) == 1 and text.count(RESULT_PREFIX) == 1 and lines[-1] == selected[0],
            "public output lacks its unique final result")
    require(re.search(r"(?:^|\n)[ \t]*(?:FAIL(?:ED)?\b|ERROR\b)|SIMX_CHECKED_COUNTER_FAILURE", text) is None
            and "CHECKED_COUNTERS_RESULT " not in text and "CHECKED_COUNTERS_FAILURE_RESULT " not in text,
            "public output is accompanied by a failure or unrelated result")
    payload = selected[0][len(RESULT_PREFIX):]
    require(len(payload.encode("utf-8")) <= MAX_RESULT_BYTES, "public result exceeds its byte bound")
    _json_depth(payload)

    def unique(pairs):
        result = {}
        for key, item in pairs:
            require(key not in result, "public result repeats a JSON key")
            result[key] = item
        return result

    def integer(token):
        require(len(token.lstrip("-")) <= 20, "public result integer exceeds its digit bound")
        return int(token)

    def unsupported(_):
        raise ValueError("public result contains a noninteger or nonfinite number")

    try:
        value = json.loads(payload, object_pairs_hook=unique, parse_int=integer,
                           parse_float=unsupported, parse_constant=unsupported)
    except (RecursionError, UnicodeError) as failure:
        raise ValueError("public result could not be decoded within its bounds") from failure
    return verify_record(value, mode)
