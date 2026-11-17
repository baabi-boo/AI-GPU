# SPDX-License-Identifier: Apache-2.0
"""Validate passive sparse-WGMMA metadata dependency observations.

The arithmetic/result validator must also accept the same complete log. This
module verifies the additional monitor state machine; output equality alone is
not evidence that a dependent instruction ever waited for metadata.
"""

import json
import re


MAX_LOG_BYTES = 16 * 1024 * 1024
MAX_TRANSACTIONS = 1024
MAX_TRANSACTION_CYCLES = 1048576
IDENTITY_KEYS = {"case_id", "format", "sparse", "mode", "a_layout", "iteration"}
BEGIN_KEYS = IDENTITY_KEYS | {"m", "n", "k", "words"}
RESULT_KEYS = IDENTITY_KEYS | {"checked", "mismatches", "actual_bits", "expected_bits"}
EVENT_KEYS = {"event", "instance", "wis", "epoch", "sequence", "cycle", "load_pc",
              "load_uuid", "load_cta", "wid", "pc", "uuid", "cta", "wait_cycles"}
INSTANCE = re.compile(r"[A-Za-z0-9_.:/-]{1,192}\Z")
HEX = re.compile(r"0x[0-9a-f]{1,16}\Z")


def _require(condition, message):
    if not condition:
        raise ValueError("WGMMA witness: " + message)


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def _record(payload):
    def reject_constant(_):
        raise ValueError("WGMMA witness: nonfinite JSON constant")

    record = json.loads(payload, object_pairs_hook=_unique_json, parse_constant=reject_constant)
    _require(type(record) is dict, "record must be a JSON object")
    return record


def _integer(value, low, high):
    return type(value) is int and low <= value <= high


def _event(record):
    _require(set(record) == EVENT_KEYS, "incorrect metadata event fields")
    _require(record["event"] in ("reserve", "wait", "release", "issue"), "unknown metadata event")
    _require(type(record["instance"]) is str and INSTANCE.fullmatch(record["instance"]),
             "invalid scoreboard instance")
    for field, low, high in (("wis", 0, 1), ("wid", 0, 7), ("load_cta", 0, 7),
                             ("cta", 0, 7), ("epoch", 1, 2**32 - 1),
                             ("sequence", 1, MAX_TRANSACTIONS), ("cycle", 0, 2**64 - 1),
                             ("wait_cycles", 0, MAX_TRANSACTION_CYCLES - 1)):
        _require(_integer(record[field], low, high), "invalid " + field)
    for field in ("load_pc", "pc", "load_uuid", "uuid"):
        _require(type(record[field]) is str and HEX.fullmatch(record[field]), "invalid " + field)
    _require(record["wid"] // 4 == record["wis"], "warp does not belong to the local slot")
    _require(record["cta"] == record["load_cta"], "instruction and metadata ownership differ")
    return record


def _load_identity(record):
    return tuple(record[key] for key in ("load_pc", "load_uuid", "load_cta", "wid"))


def _instruction_identity(record):
    return tuple(record[key] for key in ("pc", "uuid", "cta"))


def verify_witness(text, require_wait=True):
    """Return bounded per-launch coverage or reject an incomplete/invalid log.

    ``require_wait=False`` is for diagnosing an uncovered execution only. Formal
    witness runs use the default and require an actual wait in each launch.
    Every mode requires the complete eight-warp, two-CTA metadata inventory.
    Epochs distinguish simulator resets; sequence numbers otherwise continue
    across launches. Neither a reused UUID nor an unrelated writeback can close
    a transaction belonging to another instruction or local warp.
    """
    _require(type(text) is str and len(text.encode("utf-8")) <= MAX_LOG_BYTES, "log exceeds its budget")
    _require(type(require_wait) is bool, "require_wait must be boolean")
    _require(not any(ord(char) < 32 and char not in "\t\r\n" for char in text), "invalid control byte")
    _require(not re.search(r"(?:^|\n).*?(?:error:|fatal:|Assertion .*failed|Segmentation fault|"
                           r"core dumped|runtime error:|WGMMA verification failed)", text, re.IGNORECASE),
             "failure diagnostic in processor log")
    launches = []
    current = None
    passed = False
    case_id = None
    active = {}
    last_sequences = {}
    last_cycles = {}
    last_epochs = {}
    instance_slots = {}
    event_count = 0

    for line in text.splitlines():
        if not line.startswith("P02_WGMMA_"):
            _require("P02_WGMMA_" not in line, "malformed marker")
            continue
        prefix, separator, payload = line.partition(" ")
        _require(separator and prefix in ("P02_WGMMA_BEGIN", "P02_WGMMA_RESULT",
                                          "P02_WGMMA_PASS", "P02_WGMMA_META"), "unknown marker")
        _require(not passed, "record follows final pass")
        record = _record(payload)

        if prefix == "P02_WGMMA_BEGIN":
            _require(set(record) == BEGIN_KEYS and current is None and len(launches) < 2,
                     "duplicate or out-of-order begin")
            _require(type(record["case_id"]) is str and 0 < len(record["case_id"]) <= 128,
                     "invalid case identity")
            _require(record["format"] == "fp16" and record["sparse"] is True
                     and record["mode"] == "ss" and record["a_layout"] == "row-major-compressed",
                     "witness requires the frozen sparse FP16 SS case")
            _require(all(type(record[key]) is int and record[key] == value for key, value in {
                "iteration": len(launches), "m": 64, "n": 8, "k": 16, "words": 512}.items()),
                "invalid launch order or dimensions")
            _require(case_id is None or record["case_id"] == case_id, "case changed between launches")
            case_id = record["case_id"]
            current = {"identity": {key: record[key] for key in IDENTITY_KEYS}, "slots": {}, "epochs": {}}
            continue

        if prefix == "P02_WGMMA_PASS":
            _require(current is None and not active and len(launches) == 2,
                     "pass precedes two complete launches")
            _require(set(record) == {"case_id", "iterations", "checked"}
                     and type(record["iterations"]) is int and type(record["checked"]) is int
                     and record == {"case_id": case_id, "iterations": 2, "checked": 1024},
                     "invalid final pass")
            passed = True
            continue

        _require(current is not None, "metadata or result outside a launch")
        if prefix == "P02_WGMMA_RESULT":
            _require(set(record) == RESULT_KEYS and all(record.get(key) == value
                     for key, value in current["identity"].items()), "result does not match its begin")
            _require(type(record["iteration"]) is int and record["sparse"] is True
                     and type(record["checked"]) is int and record["checked"] == 512
                     and type(record["mismatches"]) is int and record["mismatches"] == 0,
                     "incomplete arithmetic result")
            _require(not active, "unfinished metadata transaction at launch end")
            slots = [current["slots"][key] for key in sorted(current["slots"])]
            transaction_count = sum(slot["transaction_count"] for slot in slots)
            waited_count = sum(slot["waited_transaction_count"] for slot in slots)
            _require(transaction_count == 16, "launch requires exactly 16 metadata transactions")
            _require(len(slots) == 8 and {slot["wid"] for slot in slots} == set(range(8)),
                     "launch requires all eight physical warps")
            _require(all(slot["transaction_count"] == 2 for slot in slots),
                     "launch requires exactly two transactions per warp")
            instance_warps = {}
            cta_warps = {}
            for slot in slots:
                instance_warps.setdefault(slot["instance"], set()).add(slot["wis"])
                cta_warps.setdefault(slot["cta"], set()).add(slot["wid"])
            _require(len(instance_warps) == 4 and all(warps == {0, 1} for warps in instance_warps.values()),
                     "launch requires four issue instances with both local warps")
            _require(len(cta_warps) == 2 and all(len(warps) == 4 for warps in cta_warps.values()),
                     "launch requires two CTAs with four warps each")
            _require(not require_wait or waited_count > 0, "zero actual metadata waits in launch")
            launches.append({**current["identity"], "transaction_count": transaction_count,
                             "waited_transaction_count": waited_count,
                             "wait_cycles": sum(slot["wait_cycles"] for slot in slots),
                             "per_slot": slots,
                             "cta_groups": [{"cta": cta, "warps": sorted(warps)}
                                            for cta, warps in sorted(cta_warps.items())]})
            current = None
            continue

        _require(len(line) <= 2048, "oversized metadata record")
        event_count += 1
        _require(event_count <= 2 * 8 * MAX_TRANSACTIONS * 4, "too many metadata records")
        record = _event(record)
        instance, wis = record["instance"], record["wis"]
        slot = (instance, wis)
        epoch_key = (instance, record["epoch"])
        sequence_key = (instance, wis, record["epoch"])
        slot_index = record["wid"] % 4
        _require(instance_slots.get(instance, slot_index) == slot_index,
                 "scoreboard instance changed issue slot")
        _require(not any(other != instance and value == slot_index for other, value in instance_slots.items()),
                 "two scoreboard instances claim the same issue slot")
        instance_slots[instance] = slot_index
        _require(len(instance_slots) <= 4, "too many issue instances")
        _require(record["epoch"] >= last_epochs.get(instance, record["epoch"]), "reset epoch moved backwards")
        _require(current["epochs"].get(instance, record["epoch"]) == record["epoch"],
                 "reset occurred inside a launch")
        current["epochs"][instance] = record["epoch"]
        last_epochs[instance] = record["epoch"]
        _require(record["cycle"] >= last_cycles.get(epoch_key, 0), "cycle moved backwards")
        last_cycles[epoch_key] = record["cycle"]

        if record["event"] == "reserve":
            _require(slot not in active, "overlapping reservation")
            _require(record["sequence"] == last_sequences.get(sequence_key, 0) + 1,
                     "duplicate, skipped, or reset sequence number")
            _require(_instruction_identity(record) == _load_identity(record)[:3]
                     and record["wait_cycles"] == 0, "reservation identity mismatch")
            last_sequences[sequence_key] = record["sequence"]
            active[slot] = {"reserve": record}
            continue

        _require(slot in active, "event lacks a reservation")
        transaction = active[slot]
        reserve = transaction["reserve"]
        _require(record["epoch"] == reserve["epoch"] and record["sequence"] == reserve["sequence"]
                 and _load_identity(record) == _load_identity(reserve), "metadata identity changed")
        _require(0 < record["cycle"] - reserve["cycle"] < MAX_TRANSACTION_CYCLES,
                 "invalid metadata transaction duration")

        if record["event"] == "wait":
            _require("wait" not in transaction and "release" not in transaction, "late or duplicate wait")
            _require(record["wait_cycles"] == 1 and record["pc"] != reserve["pc"],
                     "invalid first dependency wait")
            transaction["wait"] = record
        elif record["event"] == "release":
            _require("release" not in transaction, "duplicate metadata release")
            _require(_instruction_identity(record) == _load_identity(reserve)[:3],
                     "release belongs to another instruction")
            wait = transaction.get("wait")
            expected_waits = record["cycle"] - wait["cycle"] if wait else 0
            _require((wait is None or expected_waits > 0) and record["wait_cycles"] == expected_waits,
                     "release wait count disagrees with observed busy interval")
            transaction["release"] = record
        else:
            _require("release" in transaction, "issue precedes metadata release")
            release = transaction["release"]
            _require(record["cycle"] >= release["cycle"] and record["wait_cycles"] == release["wait_cycles"]
                     and record["pc"] != reserve["pc"], "invalid issue after metadata release")
            wait = transaction.get("wait")
            _require(wait is None or _instruction_identity(record) == _instruction_identity(wait),
                     "issued instruction differs from the actual waiter")
            if slot not in current["slots"]:
                current["slots"][slot] = {"instance": instance, "wis": wis, "wid": record["wid"],
                    "cta": record["load_cta"],
                    "epoch": record["epoch"], "transaction_count": 0, "waited_transaction_count": 0,
                    "wait_cycles": 0, "first_reserve_cycle": reserve["cycle"],
                    "last_issue_cycle": record["cycle"]}
            coverage = current["slots"][slot]
            _require(coverage["cta"] == record["load_cta"], "warp changed CTA within a launch")
            coverage["transaction_count"] += 1
            coverage["waited_transaction_count"] += int(wait is not None)
            coverage["wait_cycles"] += record["wait_cycles"]
            coverage["last_issue_cycle"] = record["cycle"]
            del active[slot]

    _require(passed and len(launches) == 2 and current is None and not active, "missing complete witness results")
    return {"launches": launches, "launch_count": len(launches), "event_count": event_count,
            "transaction_count": sum(launch["transaction_count"] for launch in launches),
            "waited_transaction_count": sum(launch["waited_transaction_count"] for launch in launches),
            "wait_cycles": sum(launch["wait_cycles"] for launch in launches),
            "coverage_requirement": "nonzero_wait_each_launch" if require_wait else "observation_only"}
