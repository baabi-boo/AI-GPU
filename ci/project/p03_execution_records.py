# SPDX-License-Identifier: Apache-2.0
"""Validate managed-operator compiler records and independently checked outputs."""

import hashlib
import json
from pathlib import Path
import re

from baseline_packet_contract import _stamp_words
from compiler_records import _records, _syntax
from p02_matrix_records import _record, require, HEX_WORD


def validate_records(runtime, backend, application, *, driver, fmt, source, build, jobs):
    require(driver in ("simx", "rtlsim") and fmt in ("fp16", "bf16"), "unsupported variant")
    runtime_lines = _records(runtime, "runtime stamp")
    backend_lines = _records(backend, "backend stamp")
    app_lines = _records(application, "operator stamp")
    require(len(runtime_lines) == 1 and len(app_lines) == 3,
            "expected separate runtime, kernel, host and linker records")
    roles = ("verilator", "backend_cpp") if driver == "rtlsim" else ("backend_cpp",)
    require(len(backend_lines) == len(roles), "incorrect backend record count")
    records = [(runtime_lines[0], "runtime"), *zip(backend_lines, roles),
               (app_lines[0], "kernel"), (app_lines[1], "host")]
    result = [_record(text, role + " stamp", fmt, role=role, source=Path(source), jobs=jobs,
                      selectors=not (driver == "rtlsim" and role == "backend_cpp"))
              for text, role in records]
    _syntax(app_lines[2], "operator linker stamp")
    require(_stamp_words(app_lines[2], "operator linker stamp") ==
            ["-L" + str(Path(build) / "sw/runtime"), "-lvortex"],
            "operator linker differs from the qualified runtime binding")
    return result


def qualification_id(binding):
    return hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "duplicate result field")
        value[key] = item
    return value


RESULT_KEYS = {"case_id", "format", "m", "n", "k", "iteration", "checked", "mismatches",
               "actual_bits", "qualification_id", "dispatch", "resources"}
DISPATCH_KEYS = {"a_address", "b_address", "d_address", "a_bytes", "b_bytes", "d_bytes",
                 "writes", "reads", "launches", "waits", "poison", "argument_bytes"}
RESOURCE_KEYS = {"used_before", "used_after", "free_before", "free_after", "primary", "cleanup"}


def verify_output(text, case, iterations, binding_id):
    require(type(iterations) is int and iterations in (1, 2), "invalid launch count")
    require(re.fullmatch(r"[0-9a-f]{64}", binding_id), "invalid execution binding")
    require(not any(ord(char) < 32 and char not in "\t\n\r" for char in text),
            "operator log contains control bytes")
    require(not re.search(r"\b(?:FAILED|FAIL|ERROR|FATAL|ABORTED|MISMATCH)\b|"
                          r"Segmentation fault|runtime error:", text, re.IGNORECASE),
            "operator log contains a failure")
    lines = text.splitlines()
    require(lines.count("PASSED!") == 1 and lines[-1] == "PASSED!"
            and len(re.findall(r"\bPASSED\b", text)) == 1, "missing or ambiguous final success record")
    results = []
    for line in lines:
        if "P03_RESULT" not in line:
            continue
        require(line.startswith("P03_RESULT "), "malformed result marker")
        row = json.loads(line[11:], object_pairs_hook=_object,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite result")))
        require(type(row) is dict and set(row) == RESULT_KEYS, "incorrect result fields")
        require(row["case_id"] == case["id"] and row["format"] == case["format"]
                and row["qualification_id"] == binding_id, "result identity differs")
        for key in ("m", "n", "k", "iteration", "checked", "mismatches"):
            require(type(row[key]) is int, "result numbers must be integers")
        require(all(row[key] == case[key] for key in ("m", "n", "k")), "result shape differs")
        require(row["iteration"] == len(results) and row["checked"] == case["m"] * case["n"]
                and row["mismatches"] == 0, "incomplete or reordered result")
        require(type(row["actual_bits"]) is list and all(type(word) is str and HEX_WORD.fullmatch(word)
                for word in row["actual_bits"]) and row["actual_bits"] == case["expected"],
                "device output differs from the independent fixture")
        dispatch, resources = row["dispatch"], row["resources"]
        require(type(dispatch) is dict and set(dispatch) == DISPATCH_KEYS, "incomplete dispatch trace")
        require(type(resources) is dict and set(resources) == RESOURCE_KEYS, "incomplete resource record")
        require(all(type(value) is int and value >= 0 for value in resources.values()),
                "invalid resource counts")
        require(resources["primary"] == resources["cleanup"] == 0
                and resources["used_before"] == resources["used_after"]
                and resources["free_before"] == resources["free_after"], "resources did not return to baseline")
        require(all(type(value) is int and value >= 0 for key, value in dispatch.items()
                    if key != "argument_bytes"), "invalid dispatch counts")
        sizes = (case["m"] * case["k"] * 2, case["k"] * case["n"] * 2, case["m"] * case["n"] * 4)
        require([dispatch[key] for key in ("a_bytes", "b_bytes", "d_bytes")] == list(sizes),
                "transfer byte counts differ")
        require((dispatch["writes"], dispatch["reads"], dispatch["launches"]) == (3, 1, 1)
                and dispatch["waits"] >= 1, "actual transfer/launch/wait trace is incomplete")
        require(dispatch["poison"] == (0x7FC0DEAD if len(results) == 0 else 0xDEADBEEF),
                "output was not independently poisoned before each launch")
        wire = dispatch["argument_bytes"]
        require(type(wire) is str and re.fullmatch(r"[0-9a-f]{112}", wire), "invalid argument bytes")
        expected = b"".join(value.to_bytes(4, "little") for value in
                            (1, 56, 1 if case["format"] == "fp16" else 2, 0,
                             case["m"], case["n"], case["k"], 0))
        ranges = []
        for key, size in zip(("a_address", "b_address", "d_address"), sizes):
            address = dispatch[key]
            require(address % 4 == 0 and address <= (1 << 64) - size, "invalid allocation address")
            ranges.append((address, address + size))
            expected += address.to_bytes(8, "little")
        require(all(a[1] <= b[0] or b[1] <= a[0] for i, a in enumerate(ranges) for b in ranges[i + 1:]),
                "operand allocations overlap")
        require(bytes.fromhex(wire) == expected, "dispatched ABI differs from the checked request")
        results.append(row)
    require(len(results) == iterations, "missing or extra operator launches")
    return results
