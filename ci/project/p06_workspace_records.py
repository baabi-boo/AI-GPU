# SPDX-License-Identifier: Apache-2.0
"""Pure, fail-closed readers for the frozen serial workspace correctness smoke.

Only trusted local validation helpers are imported. Source snapshots and native
logs are data, never code to execute. A successful result proves the recorded
native buffer/device observations; the four wrappers do not observe transient
queue/event/enqueue calls inside rejected probes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat

import p02_wmma_fixtures as fixtures
from p02_matrix_records import require
from p06_workspace_compiler_records import validate_records


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = "ci/project/p06_workspace_contract.json"
CONTRACT_ID = "p06-serial-workspace-correctness-v1"
MAX_MANIFEST_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_RECORD_BYTES = 256 * 1024
MAX_UINT64 = (1 << 64) - 1
HEX_WORD = re.compile(r"[0-9a-f]{8}\Z")
_FROZEN = {
    "schema_version": 1,
    "contract_id": CONTRACT_ID,
    "scope": "native-correctness-and-managed-ownership",
    "profile": "p02-tfr",
    "xlen": 64,
    "backends": ["simx", "rtlsim"],
    "formats": ["fp16", "bf16"],
    "policies": ["per_operation", "reusable_single_tile"],
    "shape": [8, 4, 8],
    "operand_bytes": [128, 64, 128],
    "sequence": [
        {"fixture_suffix": "single-dense_boundaries", "poison": 0xDEADBEEF},
        {"fixture_suffix": "numerical-zero", "poison": 0x7FC0DEAD},
        {"fixture_suffix": "single-k03", "poison": 0xDEADBEEF},
        {"fixture_suffix": "single-dense_boundaries", "poison": 0x7FC0DEAD},
    ],
    "per_process": {
        "launches": 4, "checked_words": 128, "peak_requested_payload_bytes": 320,
        "per_operation_buffer_creates": 12, "per_operation_buffer_releases": 12,
        "resident_buffer_creates": 3, "resident_buffer_releases": 3,
    },
    "complete_matrix": {"processes": 8, "launches": 32, "checked_words": 1024},
    "performance_acceptance": False,
    "phase_acceptance": False,
}
IDENTITY_KEYS = {"schema_version", "contract_id", "qualification_id", "policy", "format"}
RESULT_KEYS = IDENTITY_KEYS | {
    "sequence_index", "case_id", "m", "n", "k", "poison", "checked", "mismatches",
    "actual_bits", "dispatch", "results", "probes", "resources", "passed",
}
SUMMARY_KEYS = IDENTITY_KEYS | {
    "operations", "checked", "mismatches", "passed", "counts", "results",
    "unsupported_shape", "devices", "buffers",
}
COUNT_KEYS = {
    "device_open_calls", "device_release_calls", "buffer_create_calls",
    "buffer_release_calls", "live_buffers", "live_requested_bytes",
    "peak_requested_payload_bytes", "premature_releases", "errors",
}
DISPATCH_KEYS = {
    "a_address", "b_address", "d_address", "a_bytes", "b_bytes", "d_bytes",
    "writes", "launches", "reads", "waits", "timed_out_waits", "argument_bytes",
    "event_results", "profiling_enabled",
}
PROBE_NAMES = (
    "context_before_wait", "operation_before_wait", "owner_close_before_wait",
    "context_after_wait", "operation_after_wait", "owner_close_after_wait",
)
RESOURCE_NAMES = ("before_submit", "after_submit", "after_wait", "after_close")
BUFFER_KEYS = {
    "buffer_id", "device_id", "requested_bytes", "flags", "address", "address_status",
    "create_status", "create_phase", "create_sequence", "create_before", "create_after",
    "release_status", "release_phase", "release_sequence", "release_device_live",
    "release_before", "release_after",
}


def _keys(value, wanted, label):
    require(type(value) is dict and set(value) == set(wanted),
            label + " has missing or unexpected fields")


def _exact(value, expected, label):
    """Equality with recursive exact types (Python's True == 1 is insufficient)."""
    require(type(value) is type(expected), label + " has the wrong type")
    if type(expected) is dict:
        _keys(value, expected, label)
        for key, item in expected.items():
            _exact(value[key], item, label + "." + key)
    elif type(expected) is list:
        require(len(value) == len(expected), label + " has the wrong length")
        for index, item in enumerate(expected):
            _exact(value[index], item, label + "[" + str(index) + "]")
    else:
        require(value == expected, label + " differs from the frozen contract")


def _uint(value, label, maximum=MAX_UINT64):
    require(type(value) is int and 0 <= value <= maximum,
            label + " must be a bounded unsigned integer, not a boolean or float")
    return value


def _text(value, limit, label):
    require(type(value) is str, label + " must be text")
    try:
        size = len(value.encode("utf-8", errors="strict"))
    except UnicodeError as error:
        raise ValueError(label + " contains invalid Unicode") from error
    require(size <= limit, label + " exceeds its byte limit")
    require(not any((ord(char) < 32 and char not in "\t\n\r")
                    or 127 <= ord(char) <= 159
                    or (char.isspace() and char not in " \t\n\r") for char in value),
            label + " contains unsupported controls or record separators")


def _unique(pairs):
    result = {}
    for key, item in pairs:
        require(key not in result, "duplicate workspace JSON field: " + key)
        result[key] = item
    return result


def _integer(token):
    require(len(token.lstrip("-")) <= 20, "workspace JSON integer is too large")
    return int(token)


def _reject_number(_):
    raise ValueError("floating-point and nonfinite workspace JSON numbers are forbidden")


def _json(text, label, limit=MAX_RECORD_BYTES):
    _text(text, limit, label)
    depth = 0
    quoted = escaped = False
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
            require(depth <= 16, label + " exceeds the nesting limit")
        elif char in "]}":
            depth -= 1
    try:
        value = json.loads(text, object_pairs_hook=_unique, parse_int=_integer,
                           parse_float=_reject_number, parse_constant=_reject_number)
    except (UnicodeError, ValueError, RecursionError, OverflowError) as error:
        raise ValueError("invalid " + label + ": " + str(error)) from error
    require(type(value) is dict, label + " root must be an object")
    return value


def load_contract(source=ROOT):
    """Read the source manifest as bounded data and require the exact freeze."""
    path = Path(source) / MANIFEST_PATH
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_size <= MAX_MANIFEST_BYTES,
                "workspace contract must be a bounded regular file")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            data = stream.read(MAX_MANIFEST_BYTES + 1)
        require(len(data) <= MAX_MANIFEST_BYTES, "workspace contract grew beyond its byte limit")
        contract = _json(data.decode("utf-8", errors="strict"), "workspace contract",
                         MAX_MANIFEST_BYTES)
    except (OSError, UnicodeError) as error:
        raise ValueError("cannot read workspace contract: " + str(error)) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    _exact(contract, _FROZEN, "workspace contract")
    return contract


def _cases(cases, fmt, contract):
    require(type(cases) is list and len(cases) == 4,
            "workspace cases must be the ordered four-row source fixture sequence")
    # The caller supplies source-bound cases. Compare them to the trusted local
    # independent P02 producers as well, without importing a retained snapshot.
    inventory = {case["id"]: case for case in fixtures.load_cases(ROOT)}
    for index, selection in enumerate(contract["sequence"]):
        expected = inventory[fmt + "-" + selection["fixture_suffix"]]
        _exact(cases[index], expected, "workspace fixture " + str(index))
        require([cases[index][key] for key in ("m", "n", "k")] == [8, 4, 8],
                "workspace fixture shape differs")
        if index:
            require(cases[index]["a_words"] != cases[index - 1]["a_words"]
                    and cases[index]["b_words"] != cases[index - 1]["b_words"],
                    "both workspace inputs must change at each adjacent transition")


def _identity(value, fmt, policy, binding_id, label):
    for key, expected in (
            ("schema_version", 1), ("contract_id", CONTRACT_ID),
            ("qualification_id", binding_id), ("format", fmt), ("policy", policy)):
        _exact(value[key], expected, label + "." + key)


def _result(value, label, *, validation=0, primary=0, complete=True):
    _exact(value, {"validation": validation, "primary": primary,
                   "cleanup": 0, "complete": complete}, label)


def _memory(value, label):
    _keys(value, {"status", "free_bytes", "used_bytes"}, label)
    _exact(value["status"], 0, label + ".status")
    for key in ("free_bytes", "used_bytes"):
        _uint(value[key], label + "." + key)
    require(0 < value["free_bytes"] + value["used_bytes"] <= MAX_UINT64,
            label + " has an invalid memory capacity")
    return value


def _expected_counts(creates, releases, live, peak, *, device_releases=0):
    return {"device_open_calls": 1, "device_release_calls": device_releases,
            "buffer_create_calls": creates, "buffer_release_calls": releases,
            "live_buffers": 3 if live else 0,
            "live_requested_bytes": 320 if live else 0,
            "peak_requested_payload_bytes": peak, "premature_releases": 0, "errors": 0}


def _counts(value, expected, label):
    _keys(value, COUNT_KEYS, label)
    for key in COUNT_KEYS:
        _uint(value[key], label + "." + key)
    _exact(value, expected, label)


def _probe(value, expected_counts, label, *, owner_close=False, unsupported=False, resident=False):
    fields = {"result", "returned_object", "before", "after"}
    _keys(value, fields | ({"m", "n", "k"} if unsupported else set()), label)
    _result(value["result"], label + ".result", validation=5 if unsupported else 0,
            primary=0 if unsupported else 7, complete=not owner_close)
    _exact(value["returned_object"], False, label + ".returned_object")
    _counts(value["before"], expected_counts, label + ".before")
    _counts(value["after"], expected_counts, label + ".after")
    if unsupported:
        for key, expected in zip(("m", "n", "k"), (8, 4, 16) if resident else (7, 4, 8)):
            _exact(value[key], expected, label + "." + key)


def _dispatch(value, fmt, label):
    _keys(value, DISPATCH_KEYS, label)
    for key, expected in (("a_bytes", 128), ("b_bytes", 64), ("d_bytes", 128),
                          ("writes", 3), ("launches", 1), ("reads", 1),
                          ("waits", 1), ("timed_out_waits", 0)):
        _exact(value[key], expected, label + "." + key)
    _exact(value["event_results"], [0] * 5, label + ".event_results")
    _exact(value["profiling_enabled"], False, label + ".profiling_enabled")
    addresses = [_uint(value[key], label + "." + key)
                 for key in ("a_address", "b_address", "d_address")]
    sizes = (128, 64, 128)
    for address, size in zip(addresses, sizes):
        require(address % 4 == 0 and address <= MAX_UINT64 - size,
                label + " has a misaligned or overflowing allocation extent")
    require(all(a + sizes[i] <= b or b + sizes[j] <= a
                for i, a in enumerate(addresses) for j, b in enumerate(addresses) if i < j),
            label + " has overlapping operand extents")
    wire = value["argument_bytes"]
    require(type(wire) is str and re.fullmatch(r"[0-9a-f]{112}", wire) is not None,
            label + " must retain all 56 argument bytes as lowercase hex")
    expected = b"".join(word.to_bytes(4, "little") for word in
                        (1, 56, 1 if fmt == "fp16" else 2, 0, 8, 4, 8, 0))
    expected += b"".join(address.to_bytes(8, "little") for address in addresses)
    require(bytes.fromhex(wire) == expected, label + " does not match the actual frozen ABI")
    return addresses


def _operation(row, case, index, fmt, policy, binding_id, contract):
    label = "workspace operation " + str(index)
    _keys(row, RESULT_KEYS, label)
    _identity(row, fmt, policy, binding_id, label)
    for key, expected in (("sequence_index", index), ("case_id", case["id"]),
                          ("m", 8), ("n", 4), ("k", 8), ("checked", 32),
                          ("mismatches", 0), ("passed", True),
                          ("poison", contract["sequence"][index]["poison"])):
        _exact(row[key], expected, label + "." + key)
    bits = row["actual_bits"]
    require(type(bits) is list and len(bits) == 32
            and all(type(word) is str and HEX_WORD.fullmatch(word) for word in bits),
            label + " must retain exactly 32 lowercase hexadecimal FP32 words")
    _exact(bits, case["expected"], label + ".actual_bits")
    _dispatch(row["dispatch"], fmt, label + ".dispatch")
    _keys(row["results"], {"submit", "wait", "close"}, label + ".results")
    for name in ("submit", "wait", "close"):
        _result(row["results"][name], label + "." + name, complete=name != "submit")
    resident = policy == "reusable_single_tile"
    before_creates, after_creates = (3, 3) if resident else (3 * index, 3 * (index + 1))
    before_releases, after_releases = (0, 0) if resident else (3 * index, 3 * (index + 1))
    expected_counts = (
        _expected_counts(before_creates, before_releases, resident, 320 if resident or index else 0),
        _expected_counts(after_creates, before_releases, True, 320),
        _expected_counts(after_creates, before_releases, True, 320),
        _expected_counts(after_creates, after_releases, resident, 320),
    )
    _keys(row["resources"], RESOURCE_NAMES, label + ".resources")
    for name, expected in zip(RESOURCE_NAMES, expected_counts):
        resource = row["resources"][name]
        _keys(resource, {"memory", "counts"}, label + "." + name)
        _memory(resource["memory"], label + "." + name + ".memory")
        _counts(resource["counts"], expected, label + "." + name + ".counts")
    _exact(row["resources"]["before_submit"]["memory"],
           row["resources"]["after_close"]["memory"], label + " idle memory restoration")
    _exact(row["resources"]["after_submit"]["memory"],
           row["resources"]["after_wait"]["memory"], label + " wait memory preservation")
    _keys(row["probes"], PROBE_NAMES, label + ".probes")
    for name in PROBE_NAMES:
        _probe(row["probes"][name], expected_counts[1], label + "." + name,
               owner_close=name.startswith("owner_close"))


def _buffer(value, index, resident):
    label = "workspace buffer " + str(index + 1)
    _keys(value, BUFFER_KEYS, label)
    for key, expected in (
            ("buffer_id", index + 1), ("device_id", 1),
            ("requested_bytes", (128, 64, 128)[index % 3]),
            ("flags", 2 if index % 3 == 2 else 1),
            ("address_status", 0), ("create_status", 0), ("release_status", 0),
            ("create_phase", "context_create" if resident else "submit"),
            ("release_phase", "owner_close" if resident else "operation_close"),
            ("create_sequence", -1 if resident else index // 3),
            ("release_sequence", -1 if resident else index // 3),
            ("release_device_live", True)):
        _exact(value[key], expected, label + "." + key)
    address = _uint(value["address"], label + ".address")
    require(address % 4 == 0 and address <= MAX_UINT64 - value["requested_bytes"],
            label + " has an invalid tracked extent")
    for name in ("create_before", "create_after", "release_before", "release_after"):
        _memory(value[name], label + "." + name)
    cb, ca, rb, ra = (value[key] for key in
                      ("create_before", "create_after", "release_before", "release_after"))
    charged = ca["used_bytes"] - cb["used_bytes"]
    # Device::mem_alloc and MemoryAllocator charge cache-block-rounded bytes.
    # Keep that measured cost distinct from requested tensor payload, and allow
    # documented additional rounding only when its exact charge is reclaimed.
    require(charged >= value["requested_bytes"] and charged % 64 == 0
            and cb["free_bytes"] - ca["free_bytes"] == charged
            and rb["used_bytes"] - ra["used_bytes"] == charged
            and ra["free_bytes"] - rb["free_bytes"] == charged,
            label + " allocation/release memory deltas do not reconcile")


def _lifetimes(operations, summary, resident):
    buffers, devices = summary["buffers"], summary["devices"]
    count = 3 if resident else 12
    require(type(buffers) is list and len(buffers) == count,
            "workspace buffer inventory does not prove every required lifetime")
    require(type(devices) is list and len(devices) == 1,
            "workspace requires exactly one actual native device lifetime")
    device = devices[0]
    _keys(device, {"device_id", "index", "open_status", "after_open",
                   "release_status", "before_release"}, "workspace device")
    for key, expected in (("device_id", 1), ("index", 0), ("open_status", 0), ("release_status", 0)):
        _exact(device[key], expected, "workspace device." + key)
    _memory(device["after_open"], "workspace device.after_open")
    _memory(device["before_release"], "workspace device.before_release")
    _exact(device["before_release"], device["after_open"],
           "workspace final live-device baseline restoration")
    readings = [device["after_open"], device["before_release"]]
    for index, buffer in enumerate(buffers):
        _buffer(buffer, index, resident)
        readings.extend(buffer[name] for name in
                        ("create_before", "create_after", "release_before", "release_after"))
    for operation in operations:
        readings.extend(operation["resources"][name]["memory"] for name in RESOURCE_NAMES)
    total = device["after_open"]["free_bytes"] + device["after_open"]["used_bytes"]
    require(all(reading["free_bytes"] + reading["used_bytes"] == total for reading in readings),
            "workspace memory readings disagree on live device capacity")

    groups = [buffers] if resident else [buffers[i:i + 3] for i in range(0, 12, 3)]
    live_payload = peak = create_count = release_count = 0
    idle_memory = None
    for group_index, group in enumerate(groups):
        # The inventory is allocation ordered. Release order is reconstructed
        # from decreasing live used bytes, not assumed to match allocation order.
        release_order = sorted(group, key=lambda row: row["release_before"]["used_bytes"], reverse=True)
        for index, buffer in enumerate(group):
            if index:
                _exact(buffer["create_before"], group[index - 1]["create_after"],
                       "workspace contiguous tensor creation memory")
            live_payload += buffer["requested_bytes"]
            create_count += 1
            peak = max(peak, live_payload)
        for index, buffer in enumerate(release_order):
            if index:
                _exact(buffer["release_before"], release_order[index - 1]["release_after"],
                       "workspace contiguous tensor release memory")
            live_payload -= buffer["requested_bytes"]
            release_count += 1
            require(live_payload >= 0, "workspace releases unowned tensor payload")
        before, live, after = group[0]["create_before"], group[-1]["create_after"], release_order[-1]["release_after"]
        _exact(release_order[0]["release_before"], live, "workspace tensor release starts at live baseline")
        _exact(after, before, "workspace tensor group restores its allocation baseline")
        if idle_memory is None:
            idle_memory = before
        _exact(before, idle_memory, "workspace idle context memory stability")
        selected = operations if resident else [operations[group_index]]
        for operation in selected:
            resources = operation["resources"]
            for name in RESOURCE_NAMES:
                expected = live if resident or name in ("after_submit", "after_wait") else before
                _exact(resources[name]["memory"], expected, "workspace snapshot and allocation reconciliation")
            addresses = [operation["dispatch"][name] for name in ("a_address", "b_address", "d_address")]
            _exact(addresses, [buffer["address"] for buffer in group],
                   "workspace dispatch addresses and tracked tensor ownership")
    require(create_count == release_count == count and peak == 320 and live_payload == 0,
            "workspace event-derived tensor lifetime accounting differs")
    require(idle_memory["used_bytes"] >= device["after_open"]["used_bytes"]
            and idle_memory["free_bytes"] <= device["after_open"]["free_bytes"],
            "workspace context baseline predates its actual device allocation baseline")


def verify_output(text, *, cases, fmt, policy, binding_id, contract):
    """Validate one complete four-call process; return original checked records.

    The runner binds backend/source/tools and the ordered fixture list into
    binding_id. Process success does not assert that the eight-process matrix,
    performance acceptance, or phase acceptance has completed.
    """
    _exact(contract, _FROZEN, "workspace contract")
    require(type(fmt) is str and fmt in contract["formats"], "unsupported workspace format")
    require(type(policy) is str and policy in contract["policies"], "unsupported workspace policy")
    require(type(binding_id) is str and re.fullmatch(r"[0-9a-f]{64}", binding_id) is not None,
            "workspace execution binding must be lowercase SHA-256")
    _cases(cases, fmt, contract)
    _text(text, MAX_OUTPUT_BYTES, "workspace native output")
    require(not re.search(r"\b(?:FAILED|FAIL|ERROR|FATAL|ABORTED|MISMATCH)\b|"
                          r"Assertion .*failed|Segmentation fault|core dumped|runtime error:",
                          text, re.IGNORECASE), "workspace native output contains a failure marker")
    lines = text.splitlines()
    require(bool(lines) and lines[-1] == "PASSED!" and lines.count("PASSED!") == 1
            and len(re.findall(r"\bPASSED\b", text)) == 1,
            "workspace output requires exactly one unambiguous final PASSED! marker")
    operations = []
    summary = None
    for line_index, line in enumerate(lines[:-1]):
        if "P06_WORKSPACE" not in line:
            continue
        if line.startswith("P06_WORKSPACE_RESULT "):
            require(summary is None and len(operations) < 4,
                    "workspace result appears after summary or exceeds four calls")
            row = _json(line[len("P06_WORKSPACE_RESULT "):], "workspace result")
            index = len(operations)
            _operation(row, cases[index], index, fmt, policy, binding_id, contract)
            operations.append(row)
        elif line.startswith("P06_WORKSPACE_SUMMARY "):
            require(summary is None and len(operations) == 4,
                    "workspace summary is repeated or precedes all four results")
            require(line_index == len(lines) - 2,
                    "workspace summary must immediately precede the final success marker")
            summary = _json(line[len("P06_WORKSPACE_SUMMARY "):], "workspace summary")
        else:
            raise ValueError("malformed workspace record marker")
    require(len(operations) == 4 and summary is not None, "missing workspace operation or summary records")
    _keys(summary, SUMMARY_KEYS, "workspace summary")
    _identity(summary, fmt, policy, binding_id, "workspace summary")
    for key, expected in (("operations", 4), ("checked", 128), ("mismatches", 0), ("passed", True)):
        _exact(summary[key], expected, "workspace summary." + key)
    _keys(summary["results"], {"setup", "teardown", "teardown_repeat"}, "workspace summary.results")
    for name, result in summary["results"].items():
        _result(result, "workspace summary." + name)
    resident = policy == "reusable_single_tile"
    count = 3 if resident else 12
    _counts(summary["counts"], _expected_counts(count, count, False, 320, device_releases=1),
            "workspace final counts")
    _probe(summary["unsupported_shape"], _expected_counts(3 if resident else 0, 0, resident,
                                                        320 if resident else 0),
           "workspace unsupported-shape probe", unsupported=True, resident=resident)
    _lifetimes(operations, summary, resident)
    return {"operations": operations, "summary": summary}
