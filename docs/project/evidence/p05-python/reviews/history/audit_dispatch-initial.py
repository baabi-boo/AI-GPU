#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Audit retained P05 dispatch, lifecycle and explicit tensor traffic independently.

Inputs are extracted packet directories, never archives or executable workloads.
The default requires FP16 and BF16 at one clean source identity. --selected-scope
permits one format and records the incomplete matrix; no invocation accepts P05.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import sys
import types


MAX_BYTES = 16 * 1024 * 1024
MAX_RECORD = 256 * 1024
MAX_TOTAL = 256 * 1024 * 1024
U64 = (1 << 64) - 1
POISONS = (0x7FC0DEAD, 0xDEADBEEF)
FORMATS = {"fp16", "bf16"}
SHAPES = (("single-dense_boundaries", (8, 4, 8)),
          ("numerical-cross_tile_rounding_positive", (8, 4, 16)),
          ("multi-dense_boundaries", (16, 8, 16)))
FAMILIES = ("seeded_dense", "negated_dense", "zero", "signed_basis", "split_boundary")
HELPER = "docs/project/evidence/p04-executor/reviews/audit_dispatch.py"
HELPER_SHA = "8f83c5bf7986ef99f6580a1bea3dc645ee7736549f3af454be56fc96f9351781"
PROFILE_SHA = "79a551bd7ba51b5aa4b221eeb9c8f68b0f3078e6282ce71a1f28e9bc4593a102"
FIXTURE_SHA = "d22a899827afb3e8c22a528fc6a27fd12ff114ef39caf9ffa0cccd77e849cd03"
FIXTURES = {
    "ci/project/fixtures/p02_layout_v1.json": "0543f9f4208de3ff4743fe1894d97ccf3b8cca4707e9a26acd1f3dde884725b2",
    "ci/project/fixtures/p02_wmma_numerical_v1.json": "4102d74024e92e9887d7324b9326c0d6ad1fff206b5fad33f45c530d5bd03a73",
    "ci/project/fixtures/p04_tiny_mlp_v1.json": FIXTURE_SHA,
}
NATIVE_PINS = {
    "sw/common/ai_matmul_args.h": "732bd11a5002a4486ffe89b75f082f199f4bd2436c984ddaaae63d0748f02147",
    "sw/common/ai_matmul_profile.h": "8b2eb9a819506227808537612672c08a574230736f13f840a9d83bbd35675680",
    "sw/kernel/ai/matmul.cpp": "ad3b6107f0eef91ec676412bc795ab70cd1c9f31647b2cea854de6234fe71d3e",
    "sw/runtime/ai/contract.cpp": "0accd8d6a977b61f66035ced218b2fb95cf88287b7dec6f6286f361c3371b5ff",
    "sw/runtime/ai/contract.h": "7d6194824706b1a256c4810b131340af3f5e8e45ccb81313546507b914c33d5b",
    "sw/runtime/ai/runtime.cpp": "5540092240fb926f1c3066b0e8956a0096cb6be42b71f8b60d075434518e0be5",
    "sw/runtime/ai/runtime.h": "dc9c5f789c0a58dfbdce10420fce32f1d17c8e71fb83a7608d6e38489d4d4ad1",
    "sw/runtime/ai/mlp_runtime.cpp": "0dab325434c513b85b66b108ca3b896304ab797252b9fd01919435fc8655ddd1",
    "sw/runtime/ai/mlp_runtime.h": "56750815b71361eb036aa8000716b977569a657a2cee650f9bdd048c06b81182",
    "sw/runtime/ai/mlp_host.cpp": "de11f87400c61b166ab70913f437921ad9beed61a1aaa6ba8d35eb8eeb275256",
    "sw/runtime/ai/mlp_host.h": "309e437aa9ca80c3a9c7c8ca7544478cdce4861203d32280709e2e940425cd0b",
    "tests/regression/ai_matmul/main.cpp": "31428ef514ba3f3f8ba687fd3cecf4f032126a8e0055fd37ca6f7eab99f54317",
    "tests/regression/ai_mlp/main.cpp": "1abf4706aaa5265a4ddd959587d2095e2a01f32ad6b1ca94d30fffd8e562eb9b",
    "tests/regression/ai_mlp/records.h": "13a4d51ab7058a799b9598c0ba410b64b6bd28d77c305f88de702ef0db8daf29",
}
DISPATCH_FIELDS = set(("qualification_id input_dtype m n k poison a_address b_address d_address "
    "a_bytes b_bytes d_bytes argument_bytes writes_enqueued launches_enqueued reads_enqueued wait_calls "
    "timed_out_waits event_results profiling_enabled event_profiles event_profile_results event_profile_queried").split())
P03_DISPATCH_FIELDS = set(("a_address b_address d_address a_bytes b_bytes d_bytes writes reads "
                          "launches waits poison argument_bytes").split())
COUNTERS = ("matmul_runs", "model_runs", "matmul_launches", "model_launches", "total_launches",
            "profiled_launches", "unprofiled_launches", "event_profile_pairs", "h2d_transfers",
            "d2h_transfers", "tensor_h2d_bytes", "tensor_d2h_bytes", "argument_block_bytes",
            "host_bridge_bytes", "host_assembly_bytes")
REPORT_FIELDS = set(("schema_version contract_id started_at finished_at state outcome reason development "
    "acceptance_claimed phase_complete backend format iterations commands limitations budget paths "
    "resources_before resources_after loaded_helpers source_before source_after source_stable selection "
    "matmul_case_ids model_case_ids tools_before tools_after dependencies_before retained_sources "
    "package_tools_before package_tools_after native_input native_report native_qualification_id "
    "native_artifacts bundle_validation bundle_manifest bundle_artifacts matmul_backend_header_macros "
    "matmul_binding matmul_qualification_id matmul_compiler_records matmul_artifacts_before "
    "matmul_artifacts_after retained_native_matmul retained_native_model native_matmuls "
    "package_source_stage extracted_sdist_before_build wheel_inventory packages venv_interpreter "
    "installed_before installed_after installed_request installed_script observations comparison "
    "native_counts completed_native_and_python_launches").split())


def check(condition, message):
    if not condition:
        raise ValueError(message)


def fields(value, names, label):
    check(type(value) is dict and set(value) == set(names), label + " fields differ")


def uint(value, label):
    check(type(value) is int and 0 <= value <= U64, label + " must be uint64")
    return value


def number(value, wanted, label):
    check(uint(value, label) == wanted, label + " differs")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def same(actual, expected, label):
    check(canonical(actual) == canonical(expected), label + " differs")


def identity(value, length, label):
    check(type(value) is str and re.fullmatch(r"[0-9a-f]{" + str(length) + "}", value), label + " is invalid")
    return value


def safe_text(value, label):
    check(type(value) is str and len(value) <= 4096
          and not any(ord(c) < 32 or 127 <= ord(c) < 160 for c in value), label + " is invalid")
    return value


def member_name(value):
    safe_text(value, "member path")
    name = PurePosixPath(value)
    check(value and len(value) <= 512 and "\\" not in value and not name.is_absolute()
          and name.as_posix() == value and len(name.parts) <= 64
          and all(part not in (".", "..") for part in name.parts), "unsafe member path")
    return name


def absolute_name(value, label):
    safe_text(value, label)
    name = PurePosixPath(value)
    check(name.is_absolute() and name.as_posix() == value and ".." not in name.parts
          and "\\" not in value, label + " is not a canonical absolute path")
    return name


def plain_directory(value):
    path = Path(value)
    absolute_name(str(path), "input directory")
    check(path.resolve(strict=True) == path and path.is_dir(), "input directory is not plain and canonical")
    return path


def parse_json(data, *, record=False):
    check(type(data) is bytes and len(data) <= (MAX_RECORD if record else MAX_BYTES), "JSON exceeds byte bound")
    text = data.decode("utf-8")
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
            check(depth <= 40, "JSON nesting exceeds bound")
        elif char in "]}":
            depth -= 1
            check(depth >= 0, "JSON nesting is invalid")
    check(depth == 0 and not quoted, "JSON framing is incomplete")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            check(key not in result, "duplicate JSON key: " + key)
            result[key] = value
        return result

    def integer(token):
        check(len(token) <= 64, "JSON integer exceeds bound")
        return int(token)

    def floating(token):
        check(not record and len(token) <= 64, "noninteger record number")
        value = float(token)
        check(math.isfinite(value), "nonfinite JSON number")
        return value

    def invalid(token):
        raise ValueError("nonfinite JSON token: " + token)

    return json.loads(text, object_pairs_hook=unique, parse_int=integer,
                      parse_float=floating, parse_constant=invalid)


class Reader:
    def __init__(self, root):
        self.root = plain_directory(root)
        self.files = {}
        self.total_bytes = 0

    def read(self, relative):
        member_name(relative)
        path = self.root / relative
        check(path.resolve(strict=True) == path, "member resolves through a symlink: " + relative)
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            check(stat.S_ISREG(info.st_mode) and info.st_size <= MAX_BYTES,
                  "member is not a bounded regular file: " + relative)
            data = stream.read(MAX_BYTES + 1)
        check(len(data) <= MAX_BYTES, "member exceeds byte bound: " + relative)
        row = {"path": relative, "sha256": digest(data), "size_bytes": len(data)}
        if relative in self.files:
            same(row, self.files[relative], "member changed during audit")
        else:
            self.total_bytes += len(data)
            check(len(self.files) < 1024 and self.total_bytes <= MAX_TOTAL, "input aggregate exceeds bound")
            self.files[relative] = row
        return data

    def verified(self, descriptor, expected_path=None):
        fields(descriptor, {"path", "sha256", "size_bytes"}, "artifact descriptor")
        if expected_path is not None:
            check(descriptor["path"] == expected_path, "artifact path differs: " + expected_path)
        identity(descriptor["sha256"], 64, "artifact hash")
        data = self.read(descriptor["path"])
        number(descriptor["size_bytes"], len(data), "artifact size")
        check(digest(data) == descriptor["sha256"], "artifact hash differs: " + descriptor["path"])
        return data

    def document(self, descriptor, expected_path=None, *, record=False):
        return parse_json(self.verified(descriptor, expected_path), record=record)


def index_files(rows, label):
    check(type(rows) is list and len(rows) <= 20000, label + " inventory exceeds bound")
    result = {}
    for row in rows:
        fields(row, {"path", "sha256", "size_bytes"}, label + " descriptor")
        member_name(row["path"])
        identity(row["sha256"], 64, label + " digest")
        uint(row["size_bytes"], label + " size")
        check(row["path"] not in result, "duplicate " + label + " member")
        result[row["path"]] = row
    return result


def load_support(source):
    reader = Reader(source)
    body = reader.read(HELPER)
    check(digest(body) == HELPER_SHA, "independent P04 auditor pin differs")
    helper = types.ModuleType("p05_frozen_p04_dispatch")
    helper.__file__ = str(reader.root / HELPER)
    exec(compile(body, helper.__file__, "exec"), helper.__dict__)
    for path, expected in NATIVE_PINS.items():
        check(digest(reader.read(path)) == expected, "unchanged native source pin differs: " + path)
    documents = {}
    for path, expected in FIXTURES.items():
        raw = reader.read(path)
        check(digest(raw) == expected, "frozen fixture pin differs: " + path)
        documents[path] = parse_json(raw, record=False)
    matmuls = {row["id"]: dict(row, **row["dimensions"])
               for path, document in documents.items() if "p02_" in path for row in document["cases"]}
    model = documents["ci/project/fixtures/p04_tiny_mlp_v1.json"]
    models = {row["id"]: dict(row, **model["weights"]["formats"][row["format"]]) for row in model["cases"]}
    check(len(matmuls) == 88 and len(models) == 10, "frozen fixture inventory differs")
    return helper, matmuls, models, list(reader.files.values())


def source_identity(reader, report):
    before = reader.document(report["source_before"], "snapshots/source-before.json")
    after = reader.document(report["source_after"], "snapshots/source-after.json")
    same(before, after, "source before/after inventories")
    checkout = before["checkout"]
    check(type(checkout) is dict and checkout["dirty"] is False and checkout["blockers"] == []
          and checkout["changed_paths"] == [] and checkout["untracked_paths"] == [], "recorded source is not clean")
    identity(checkout["revision"], 40, "source revision")
    identity(checkout["tree"], 40, "source tree")
    return checkout, index_files(before["files"], "source")


def envelope(report, contract):
    check(type(report) is dict, "report must be an object")
    number(report["schema_version"], 1, "report schema")
    check(report["contract_id"] == contract and report["state"] == "finished"
          and report["outcome"] == "pass" and report["reason"] is None, "report is incomplete or unsuccessful")
    check(report["development"] is False and report["source_stable"] is True
          and report["acceptance_claimed"] is False and report["phase_complete"] is False,
          "report claims unsupported scope or unstable/development execution")
    number(report["iterations"], 2, "report repetitions")
    budget = report["budget"]
    number(budget["max_log_bytes"], MAX_BYTES, "log bound")
    check(0 < uint(budget["max_rss_bytes"], "RSS budget") <= 4 * 1024**3
          and uint(budget["min_free_bytes"], "disk reserve") >= 15 * 1024**3
          and 1 <= uint(budget["jobs"], "build jobs") <= 2, "resource budget differs")


def commands(reader, report):
    rows = report["commands"]
    check(type(rows) is list and 0 < len(rows) <= 256, "command inventory exceeds bound")
    result = {}
    for row in rows:
        check(type(row) is dict and type(row["id"]) is str
              and re.fullmatch(r"[a-z0-9_-]{1,128}", row["id"]), "invalid command ID")
        name = row["id"]
        check(name not in result, "duplicate command ID")
        check(row["outcome"] == "pass" and row["process_started"] is True
              and row["cleanup_complete"] is True and row["reason"] is None, "failed or incomplete command: " + name)
        number(row["exit_code"], 0, "command exit")
        check(0 < uint(row["timeout_seconds"], "command deadline") <= 2940
              and uint(row["peak_rss_bytes"], "command RSS") <= report["budget"]["max_rss_bytes"], "command exceeds bound")
        check(type(row["argv"]) is list and 0 < len(row["argv"]) <= 128, "invalid command arguments")
        for argument in row["argv"]:
            safe_text(argument, "command argument")
        absolute_name(row["cwd"], "command cwd")
        check(type(row["environment"]) is dict, "invalid command environment")
        raw = reader.verified({"path": row["log"], "sha256": row["log_sha256"],
                               "size_bytes": row["log_size_bytes"]}, "logs/" + name + ".log")
        result[name] = (row, raw)
    return result


def raw_rows(raw, markers, *, native=False):
    text = raw.decode("utf-8")
    check(not any(ord(c) < 32 and c not in "\n\r\t" or 127 <= ord(c) < 160 for c in text),
          "control character in execution log")
    check(not re.search(r"\b(?:FAILED|FAILURE|FAIL|ERROR|FATAL|ABORTED|MISMATCH)\b|P0[345]_(?:FAILURE|DRAIN|CLEANUP)|"
                        r"Segmentation fault|runtime error:", text, re.IGNORECASE), "failure text in execution log")
    lines = text.splitlines()
    if native:
        check(lines and lines[-1] == "PASSED!" and lines.count("PASSED!") == 1
              and len(re.findall(r"\bPASSED\b", text, re.IGNORECASE)) == 1, "native final framing differs")
    result = []
    for line in lines:
        if re.search(r"P0[345]_(?:RESULT|MATMUL|MODEL)", line, re.IGNORECASE):
            marker = next((item for item in markers if line.startswith(item + " ")), None)
            check(marker is not None, "unexpected or ambiguous raw observation marker")
            result.append((marker, parse_json(line[len(marker) + 1:].encode("utf-8"), record=True)))
    return result


def successful(value, *, python=False):
    same(value, {"validation": "success" if python else 0, "primary": 0, "cleanup": 0, "complete": True},
         "completed execution/cleanup status")


def words(value, count, label):
    check(type(value) is list and len(value) == count and all(
        type(word) is str and re.fullmatch(r"[0-9a-f]{8}", word) for word in value), label + " words differ")
    return value


def packed(value):
    return b"".join(int(word, 16).to_bytes(4, "little") for word in value)


def memory_restored(memory, *, native=False):
    expected = {"free_before", "free_after", "used_before", "used_after"}
    expected |= {"primary", "cleanup"} if native else {"before_status", "after_status"}
    fields(memory, expected, "matmul resources")
    for name, value in memory.items():
        uint(value, "memory " + name)
    for name in ({"primary", "cleanup"} if native else {"before_status", "after_status"}):
        number(memory[name], 0, name)
    for kind in ("free", "used"):
        check(memory[kind + "_before"] == memory[kind + "_after"], "memory baseline was not restored")


def audit_abi(dispatch, shape, fmt, poison, *, native=False):
    m, n, k = shape
    sizes = (m * k * 2, k * n * 2, m * n * 4)
    for key, expected in zip(("a_bytes", "b_bytes", "d_bytes"), sizes):
        number(dispatch[key], expected, "tensor extent " + key)
    number(dispatch["poison"], poison, "destination poison")
    count_names = ("writes", "launches", "reads") if native else ("writes_enqueued", "launches_enqueued", "reads_enqueued")
    for name, expected in zip(count_names, (3, 1, 1)):
        number(dispatch[name], expected, "native " + name)
    waits = uint(dispatch["waits" if native else "wait_calls"], "native waits")
    check(waits > (0 if native else uint(dispatch["timed_out_waits"], "timeout waits")), "no successful wait observed")
    addresses = [uint(dispatch[key + "_address"], key + " address") for key in ("a", "b", "d")]
    spans = []
    for address, size in zip(addresses, sizes):
        check(address % 4 == 0 and address <= (1 << 64) - size, "allocation is misaligned or overflows")
        spans.append((address, address + size))
    spans.sort()
    check(all(a[1] <= b[0] for a, b in zip(spans, spans[1:])), "native operand allocations overlap")
    wire = struct.pack("<8I3Q", 1, 56, {"fp16": 1, "bf16": 2}[fmt], 0, m, n, k, 0, *addresses).hex()
    check(type(dispatch["argument_bytes"]) is str and dispatch["argument_bytes"] == wire, "56-byte native ABI differs")
    return sizes


def audit_profiles(dispatch, previous_end, statistics, helper):
    check(dispatch["profiling_enabled"] is True, "native profiling was disabled")
    names = ("event_results", "event_profile_results", "event_profile_queried", "event_profiles")
    for name in names:
        check(type(dispatch[name]) is list and len(dispatch[name]) == 5, "five-event profile inventory differs")
    queued_before = previous_end
    end_before = previous_end
    for index, profile in enumerate(dispatch["event_profiles"]):
        number(dispatch["event_results"][index], 0, "event result")
        number(dispatch["event_profile_results"][index], 0, "profile result")
        check(dispatch["event_profile_queried"][index] is True, "event profile was not queried")
        fields(profile, {"queued_ns", "submit_ns", "start_ns", "end_ns"}, "event profile")
        queued, submitted, start, end = [uint(profile[key], "profile " + key)
            for key in ("queued_ns", "submit_ns", "start_ns", "end_ns")]
        check(queued_before <= queued <= submitted <= start <= end and end_before <= submitted,
              "event enqueue/dependency chronology differs")
        kind = "h2d" if index < 3 else "launch" if index == 3 else "d2h"
        for phase, duration in (("queue", submitted - queued), ("preparation", start - submitted), ("service", end - start)):
            helper.add_sample(statistics, "event." + kind + "." + phase, duration)
        queued_before, end_before = queued, end
    return end_before


def counts():
    return dict.fromkeys(COUNTERS, 0)


def add_launch(total, sizes, *, model, profiles):
    total["model_launches" if model else "matmul_launches"] += 1
    total["total_launches"] += 1
    total["profiled_launches" if profiles else "unprofiled_launches"] += 1
    total["event_profile_pairs"] += profiles
    total["h2d_transfers"] += 3
    total["d2h_transfers"] += 1
    total["tensor_h2d_bytes"] += sum(sizes)
    total["tensor_d2h_bytes"] += sizes[2]
    total["argument_block_bytes"] += 56


def audit_matmul(row, case, iteration, binding, total, statistics, helper, *, native=False, previous_end=0):
    expected = {"case_id", "iteration", "actual_bits", "resources"}
    expected |= {"format", "m", "n", "k", "checked", "mismatches", "qualification_id", "dispatch"} if native else {
        "status", "close_status", "trace"}
    fields(row, expected, "native matmul" if native else "Python matmul")
    check(row["case_id"] == case["id"], "matmul membership/order differs")
    number(row["iteration"], iteration, "matmul iteration")
    shape = tuple(case[name] for name in ("m", "n", "k"))
    dispatch = row["dispatch" if native else "trace"]
    fields(dispatch, P03_DISPATCH_FIELDS if native else DISPATCH_FIELDS, "matmul dispatch")
    if native:
        check(row["format"] == case["format"] and row["qualification_id"] == binding, "native matmul identity differs")
        for name, expected_number in zip(("m", "n", "k"), shape):
            number(row[name], expected_number, "native matmul " + name)
        number(row["checked"], shape[0] * shape[1], "native checked output")
        number(row["mismatches"], 0, "native mismatch count")
    else:
        successful(row["status"], python=True)
        successful(row["close_status"], python=True)
        check(dispatch["input_dtype"] == case["format"] and dispatch["qualification_id"] == binding,
              "Python matmul native identity differs")
        for name, expected_number in zip(("m", "n", "k"), shape):
            number(dispatch[name], expected_number, "Python matmul " + name)
    memory_restored(row["resources"], native=native)
    same(words(row["actual_bits"], shape[0] * shape[1], "actual output"), case["expected"], "frozen matmul output")
    sizes = audit_abi(dispatch, shape, case["format"], POISONS[iteration], native=native)
    end = previous_end if native else audit_profiles(dispatch, previous_end, statistics, helper)
    add_launch(total, sizes, model=False, profiles=0 if native else len(dispatch["event_profiles"]))
    total["matmul_runs"] += 1
    return end


def bridge_from_actual(hidden, fmt):
    result = bytearray()
    for word in hidden:
        bits = int(word, 16)
        magnitude = bits & 0x7FFFFFFF
        if magnitude:
            exponent, fraction = (magnitude >> 23), magnitude & 0x7FFFFF
            check(0 < exponent < 255, "actual hidden value is not a finite bounded integer")
            significand, shift = (1 << 23) | fraction, exponent - 150
            if shift < 0:
                magnitude, remainder = divmod(significand, 1 << -shift)
                check(remainder == 0, "actual hidden value is fractional")
            else:
                magnitude = significand << shift
            check(magnitude <= 64, "actual hidden value exceeds frozen bridge domain")
        active = 0 if bits >> 31 else magnitude
        if active:
            exponent = active.bit_length() - 1
            fraction_bits, bias = (10, 15) if fmt == "fp16" else (7, 127)
            encoded = ((exponent + bias) << fraction_bits) | ((active - (1 << exponent)) << (fraction_bits - exponent))
        else:
            encoded = 0
        result.extend(encoded.to_bytes(2, "little"))
    return bytes(result)


def audit_model(record, case, iteration, binding, revision, total, statistics, helper, previous_end=0):
    observed = helper.audit_record(record, case_id=case["id"], backend="simx", fmt=case["format"],
        revision=revision, binding=binding, iteration=iteration, statistics=statistics)
    check(previous_end <= observed["create_begin_ns"], "model precedes its completed predecessor")
    trace = record["trace"]
    actual_bridge = bridge_from_actual(trace["hidden_words"], case["format"])
    check(actual_bridge.hex() == trace["bridge_bytes"], "host bridge does not derive from actual hidden output")
    for index, stage in enumerate(trace["native"]):
        expected_a = packed(case["input_words"]) if index == 0 else actual_bridge[(index - 1) * 128:index * 128]
        expected_b = packed(case["w1_words"] if index == 0 else case["w2_words"])
        check(stage["a_bytes"] == expected_a.hex() and stage["b_bytes"] == expected_b.hex(),
              "native model inputs do not follow frozen inputs/weights and actual bridge")
        dispatch = stage["dispatch"]
        shape = (16, 8, 16) if index == 0 else (8, 4, 8)
        sizes = audit_abi(dispatch, shape, case["format"], POISONS[iteration])
        add_launch(total, sizes, model=True, profiles=len(dispatch["event_profiles"]))
    total["model_runs"] += 1
    total["host_bridge_bytes"] += len(actual_bridge)
    total["host_assembly_bytes"] += len(trace["output_words"]) * 4
    return observed["last_read_end_ns"]


def native_invocation(command, app, case_id, binding, revision=None):
    expected = [str(app / ("ai_mlp" if revision else "ai_matmul")), "--case", case_id, "--iterations", "2",
                "--module", str(app / "kernel.vxbin"), "--qualification-id", binding]
    if revision:
        expected.extend(["--backend", "simx", "--source-revision", revision])
    same(command["argv"], expected, "native invocation")
    check(command["cwd"] == str(app) and command["environment"].get("VORTEX_DRIVER") == "simx"
          and command["environment"].get("LD_LIBRARY_PATH") == str(app.parents[2] / "sw/runtime"),
          "native backend/working directory/runtime selection differs")
    check(not any(command["environment"].get(name) for name in ("LD_PRELOAD", "LD_AUDIT")), "native loader override")
    check(command["timeout_seconds"] <= 180, "native execution deadline exceeds bound")


def short_counts(total):
    return {key: total[key] for key in ("matmul_runs", "model_runs", "matmul_launches", "model_launches", "total_launches")}


def installation_identity(value, request):
    fields(value, {"python_version", "python_implementation", "executable", "prefix", "base_prefix",
        "package_file", "extension_file", "distribution_version", "build_info", "runtime_libraries"}, "installation")
    version = value["python_version"]
    check(type(version) is list and len(version) == 3 and all(type(part) is int and part >= 0 for part in version)
          and version[:2] == [3, 12] and value["python_implementation"] == "CPython"
          and value["distribution_version"] == "0.1.0", "installed interpreter/package identity differs")
    prefix = absolute_name(request["expected_prefix"], "installed prefix")
    check(value["prefix"] == str(prefix) and value["base_prefix"] != str(prefix), "installed isolation differs")
    absolute_name(value["base_prefix"], "base prefix")
    check(value["executable"] == str(prefix / "bin/python"), "installed interpreter path differs")
    package = absolute_name(value["package_file"], "installed package")
    extension = absolute_name(value["extension_file"], "installed extension")
    check(package.is_relative_to(prefix) and package.name == "__init__.py" and package.parent.name == "vortex_ai"
          and extension.parent == package.parent and re.fullmatch(r"_native\.cpython-312-[a-z0-9_-]+\.so", extension.name),
          "installed native extension layout differs")
    binding = request["binding"]
    same(value["build_info"], {"binding_api": 1, "bundle_sha256": binding["bundle_sha256"],
                             "source_sha256": binding["source_sha256"]}, "installed native build pins")
    same(value["runtime_libraries"], [binding["bundle_root"] + "/lib/" + name for name in (
        "libramulator.so", "libramulator-vortex.so", "libvortex.so", "libsimx.so", "libvortex-simx.so")],
        "observed native runtime libraries")


def audit_packet(supplied, support):
    helper, matmuls, models, source_files = support
    reader = Reader(supplied)
    report = parse_json(reader.read("report.json"))
    fields(report, REPORT_FIELDS, "P05 report")
    envelope(report, "p05-installed-python-execution-v1")
    fmt = report["format"]
    check(report["backend"] == "simx" and fmt in FORMATS, "unsupported P05 variant")
    number(report["budget"]["package_jobs"], 1, "package jobs")
    checkout, source_index = source_identity(reader, report)
    revision = checkout["revision"]
    outer_sources = index_files(report["retained_sources"], "retained source")
    command_rows = commands(reader, report)
    paths = report["paths"]
    for name in ("source", "work", "output", "native_build", "native_output"):
        absolute_name(paths[name], "recorded " + name)
    build = PurePosixPath(paths["native_build"])
    check(build.name == "simx-" + fmt, "native build variant differs")
    native_reader = Reader(reader.root / "native")
    native = parse_json(reader.verified(report["native_report"], "native/report.json"))
    envelope(native, "p04-managed-model-execution-v1")
    native_checkout, native_source_index = source_identity(native_reader, native)
    same(native_checkout, checkout, "native/Python source identity")
    check(native["full_matrix_requested"] is False and native["fixture_sha256"] == FIXTURE_SHA,
          "native packet claims unsupported matrix/fixture")
    check(type(native["variants"]) is list and len(native["variants"]) == 1, "native variant inventory differs")
    variant = native["variants"][0]
    check(variant["id"] == "simx-" + fmt and variant["backend"] == "simx" and variant["format"] == fmt
          and variant["outcome"] == "pass", "native variant differs")
    native_sources = index_files(native["retained_sources"], "native retained source")
    for path, expected in NATIVE_PINS.items():
        check(source_index[path]["sha256"] == native_source_index[path]["sha256"] == expected,
              "recorded native implementation differs: " + path)
        retained = "artifacts/source/" + path
        check(digest(native_reader.verified(native_sources[retained], retained)) == expected,
              "retained native implementation differs: " + path)
        if retained in outer_sources:
            check(digest(reader.verified(outer_sources[retained], retained)) == expected,
                  "retained Python native implementation differs: " + path)
    native_commands = commands(native_reader, native)
    model_binding = native_reader.document(variant["binding"])
    model_id = identity(variant["qualification_id"], 64, "model qualification ID")
    check(digest(canonical(model_binding)) == model_id == report["native_qualification_id"], "model binding digest differs")
    same(model_binding["source"], checkout, "model bound source")
    check(model_binding["backend"] == "simx" and model_binding["format"] == fmt
          and model_binding["profile_sha256"] == PROFILE_SHA and model_binding["fixture_sha256"] == FIXTURE_SHA,
          "model binding scope differs")
    same(model_binding["artifacts"], variant["artifacts_before"], "native bound artifacts")
    same(variant["artifacts_before"], variant["artifacts_after"], "native unchanged artifacts")
    binding = reader.document(report["matmul_binding"], "snapshots/native-matmul-binding.json")
    matmul_id = identity(report["matmul_qualification_id"], 64, "matmul qualification ID")
    check(digest(canonical(binding)) == matmul_id, "matmul binding digest differs")
    same(binding["source"], checkout, "matmul bound source")
    check(binding["backend"] == "simx" and binding["format"] == fmt and binding["profile_sha256"] == PROFILE_SHA,
          "matmul bound scope differs")
    same(binding["artifacts"], report["matmul_artifacts_before"], "matmul bound artifacts")
    same(report["matmul_artifacts_before"], report["matmul_artifacts_after"], "matmul unchanged artifacts")
    manifest_data = reader.verified(report["bundle_manifest"], "artifacts/bundle/manifest.json")
    manifest = parse_json(manifest_data)
    check(manifest["contract_id"] == "p05-python-bundle-v1" and manifest["backend"] == "simx"
          and manifest["format"] == fmt and manifest["qualification_id"] == model_id
          and manifest["source_revision"] == revision and manifest["source_tree"] == checkout["tree"]
          and manifest["profile_sha256"] == PROFILE_SHA and manifest["fixture_sha256"] == FIXTURE_SHA,
          "bundle scope/identity differs")
    same(manifest["native_binding"], model_binding, "bundle native binding")
    request = reader.document(report["installed_request"], "snapshots/installed-request.json", record=False)
    fields(request, {"schema_version", "contract_id", "binding", "matmul_cases", "model_cases", "iterations", "expected_prefix"}, "installed request")
    number(request["schema_version"], 1, "request schema")
    number(request["iterations"], 2, "request repetitions")
    check(request["contract_id"] == "p05-installed-request-v1", "request contract differs")
    expected_binding = {"backend": "simx", "format": fmt, "bundle_root": paths["output"] + "/artifacts/bundle",
        "bundle_sha256": digest(manifest_data), "source_sha256": manifest["binding_source_sha256"],
        "qualification_id": model_id, "source_revision": revision}
    identity(expected_binding["source_sha256"], 64, "binding source hash")
    same(request["binding"], expected_binding, "installed request binding")
    case_ids = [fmt + "-" + family for family, _ in SHAPES]
    model_ids = [fmt + "-" + family for family in FAMILIES]
    same(request["matmul_cases"], [matmuls[name] for name in case_ids], "frozen requested matmuls")
    same(request["model_cases"], model_ids, "requested models")
    same(report["matmul_case_ids"], case_ids, "report matmul inventory")
    same(report["model_case_ids"], model_ids, "report model inventory")
    work = PurePosixPath(paths["work"])
    check(request["expected_prefix"] == str(work / "venv"), "requested isolated prefix differs")
    installed_command, installed_log = command_rows["installed-matrix"]
    same(installed_command["argv"], [str(work / "venv/bin/python"), "-I", "-B", "-m", "vortex_ai.launch",
        "--bundle", expected_binding["bundle_root"], "--", str(work / "installed-check/p05_installed_check.py"),
        "--request", str(work / "installed-check/request.json"), "--output", str(work / "installed-check/observations.json")],
        "installed launcher invocation")
    check(installed_command["cwd"] == str(work / "installed-check")
          and not any(name in installed_command["environment"] for name in (
              "LD_PRELOAD", "LD_AUDIT", "LD_LIBRARY_PATH", "PYTHONPATH", "PYTHONHOME", "VORTEX_AI_BUNDLE")),
          "installed launcher environment/cwd differs")
    observed = reader.document(report["observations"], "artifacts/installed-observations.json")
    fields(observed, {"schema_version", "contract_id", "scope", "binding", "installation", "matmuls", "models",
                      "counts", "outcome", "acceptance_claimed"}, "installed observations")
    number(observed["schema_version"], 1, "observations schema")
    check(observed["contract_id"] == "p05-installed-observations-v1" and observed["scope"] == "simx-installed-python"
          and observed["outcome"] == "pass" and observed["acceptance_claimed"] is False, "unsupported observations scope")
    same(observed["binding"], expected_binding, "observed binding")
    installation_identity(observed["installation"], request)
    raw = raw_rows(installed_log, ("P05_MATMUL", "P05_MODEL"))
    same([marker for marker, _ in raw], ["P05_MATMUL"] * 6 + ["P05_MODEL"] * 10, "installed raw chronology")
    same([row for marker, row in raw if marker == "P05_MATMUL"], observed["matmuls"], "raw/retained Python matmuls")
    same([row for marker, row in raw if marker == "P05_MODEL"], observed["models"], "raw/retained Python models")
    python_counts, native_counts = counts(), counts()
    python_stats, native_stats = {}, {}
    same([row["id"] for row in report["native_matmuls"]], case_ids, "native matmul inventory")
    previous_end = 0
    for case_index, case_id in enumerate(case_ids):
        command, log = command_rows["native-" + case_id]
        native_invocation(command, build / "tests/regression/ai_matmul", case_id, matmul_id)
        check(log.decode("utf-8").splitlines().count("P03_REJECTIONS checked=2") == 1, "native rejection framing differs")
        rows = raw_rows(log, ("P03_RESULT",), native=True)
        check(len(rows) == 2, "native matmul repetition count differs")
        same([row for _, row in rows], report["native_matmuls"][case_index]["observations"], "raw/retained native matmuls")
        for iteration, (_, native_row) in enumerate(rows):
            case = matmuls[case_id]
            audit_matmul(native_row, case, iteration, matmul_id, native_counts, native_stats, helper, native=True)
            python_row = observed["matmuls"][case_index * 2 + iteration]
            previous_end = audit_matmul(python_row, case, iteration, model_id, python_counts, python_stats, helper, previous_end=previous_end)
            same(python_row["actual_bits"], native_row["actual_bits"], "native/Python actual matmul outputs")
    native_matmul_traffic = {key: native_counts[key] for key in ("tensor_h2d_bytes", "tensor_d2h_bytes")}
    same([row["id"] for row in variant["cases"]], model_ids, "native model inventory")
    for case_index, case_id in enumerate(model_ids):
        command, log = native_commands["simx-" + fmt + "-" + case_id]
        native_invocation(command, build / "tests/regression/ai_mlp", case_id, model_id, revision)
        rows = raw_rows(log, ("P04_RESULT",), native=True)
        check(len(rows) == 2, "native model repetition count differs")
        same([row for _, row in rows], variant["cases"][case_index]["observations"], "raw/retained native models")
        native_end = 0
        for iteration, (_, native_row) in enumerate(rows):
            case = models[case_id]
            native_end = audit_model(native_row, case, iteration, model_id, revision, native_counts, native_stats, helper, native_end)
            wrapper = observed["models"][case_index * 2 + iteration]
            fields(wrapper, {"case_id", "iteration", "record"}, "Python model wrapper")
            check(wrapper["case_id"] == case_id, "Python model membership/order differs")
            number(wrapper["iteration"], iteration, "Python model iteration")
            record = wrapper["record"]
            previous_end = audit_model(record, case, iteration, model_id, revision, python_counts, python_stats, helper, previous_end)
            for name in ("hidden_words", "bridge_bytes", "bridge_words", "output_words"):
                same(record["trace"][name], native_row["trace"][name], "native/Python actual model " + name)
            for actual_stage, native_stage in zip(record["trace"]["native"], native_row["trace"]["native"]):
                for name in ("a_bytes", "b_bytes", "output_words"):
                    same(actual_stage[name], native_stage[name], "native/Python stage " + name)
    check({name for name, (row, _) in command_rows.items() if "--case" in row["argv"]}
          == {"native-" + name for name in case_ids}, "unaccounted native matmul invocation")
    check({name for name, (row, _) in native_commands.items() if "--case" in row["argv"]}
          == {"simx-" + fmt + "-" + name for name in model_ids}, "unaccounted native model invocation")
    expected_counts = {"matmul_runs": 6, "model_runs": 10, "matmul_launches": 6, "model_launches": 30, "total_launches": 36}
    same(short_counts(python_counts), expected_counts, "derived Python counts")
    same(short_counts(native_counts), expected_counts, "derived native counts")
    same(observed["counts"], short_counts(python_counts), "observation count labels")
    same(report["native_counts"], short_counts(native_counts), "native count labels")
    comparison = {"counts": short_counts(python_counts),
        "matmul_words": sum(len(row["actual_bits"]) for row in observed["matmuls"]),
        "model_hidden_words": sum(len(row["record"]["trace"]["hidden_words"]) for row in observed["models"]),
        "model_bridge_words": sum(len(row["record"]["trace"]["bridge_words"]) for row in observed["models"]),
        "model_output_words": sum(len(row["record"]["trace"]["output_words"]) for row in observed["models"]),
        "event_profile_pairs": python_counts["event_profile_pairs"]}
    same(report["comparison"], comparison, "comparison labels")
    number(report["completed_native_and_python_launches"], python_counts["total_launches"] + native_counts["total_launches"], "combined launches")
    for key, expected in (("completed_case_executions", 5), ("completed_model_runs", native_counts["model_runs"]),
                          ("completed_launches", native_counts["model_launches"]),
                          ("tensor_h2d_bytes", native_counts["tensor_h2d_bytes"] - native_matmul_traffic["tensor_h2d_bytes"]),
                          ("tensor_d2h_bytes", native_counts["tensor_d2h_bytes"] - native_matmul_traffic["tensor_d2h_bytes"])):
        number(native[key], expected, "native model " + key)
    number(python_counts["event_profile_pairs"], 180, "Python event/profile pairs")
    number(native_counts["event_profile_pairs"], 150, "native model event/profile pairs")
    return {"packet": str(reader.root), "format": fmt, "source_revision": revision, "source_tree": checkout["tree"],
        "model_qualification_id": model_id, "matmul_qualification_id": matmul_id,
        "bundle_sha256": digest(manifest_data), "binding_source_sha256": manifest["binding_source_sha256"],
        "counts": {"python": python_counts, "native_comparison": native_counts},
        "timings_ns": {"python": python_stats, "native_model": native_stats},
        "consumed_files": sorted(list(reader.files.values()) + [dict(row, path="native/" + row["path"])
            for row in native_reader.files.values()], key=lambda row: row["path"])}


def audit_packets(source_dir, packets, selected_scope=False):
    check(type(selected_scope) is bool, "selected scope must be explicit boolean")
    check(1 <= len(packets) <= 2 and (selected_scope or len(packets) == 2), "two-format matrix is incomplete")
    support = load_support(source_dir)
    reports = [audit_packet(path, support) for path in packets]
    formats = [report["format"] for report in reports]
    check(len(set(formats)) == len(formats), "duplicate packet format")
    check(selected_scope or set(formats) == FORMATS, "two-format matrix is incomplete")
    identities = {(row["source_revision"], row["source_tree"]) for row in reports}
    check(len(identities) == 1, "packets mix source revisions or trees")
    revision, tree = next(iter(identities))
    totals = {"python": counts(), "native_comparison": counts(), "combined": counts()}
    for report in reports:
        for route in ("python", "native_comparison"):
            for name, value in report["counts"][route].items():
                totals[route][name] += value
                totals["combined"][name] += value
    return {"schema_version": 1, "audit": "p05-independent-dispatch-v1", "outcome": "pass",
        "phase_acceptance": False, "full_matrix_checked": set(formats) == FORMATS,
        "selected_scope": selected_scope, "scope": "complete-two-format-simx-installed-matrix" if set(formats) == FORMATS else "incomplete-selected-format-matrix",
        "source_revision": revision, "source_tree": tree, "formats": sorted(formats), "counts": totals,
        "profile_sha256": PROFILE_SHA, "fixture_sha256": FIXTURE_SHA,
        "independent_helper": {"path": HELPER, "sha256": HELPER_SHA, "use": "pure audit_record and duration aggregation; no P05 producer imports"},
        "auditor_sha256": digest(Reader(Path(__file__).resolve().parent).read(Path(__file__).name)),
        "trusted_source_files": support[3], "packets": sorted(reports, key=lambda row: row["format"]),
        "findings": [
            "Every required matmul has native allocation extents, exact ABI arguments, three writes, one launch, one read and a successful wait.",
            "Every model has three ordered native stages; actual hidden outputs produce its host ReLU/exact conversion bytes, consumed by both output stages.",
            "Operation/model cleanup and successful free/used memory baseline restoration are checked independently of pass/count labels.",
            "Native-only P03 comparisons expose no event profiling; only native P04 model launches contribute native comparison profiles.",
            "No CPU matmul fallback is observed: required native dispatches are present and accepted native runtime/kernel/model bodies remain hash pinned.",
        ], "limitations": [
            "Retained observations are audited without execution or authentication of the originating runner, within the trusted-builder/nonadversarial-filesystem boundary.",
            "Frozen outputs are compared where retained; independent numerical dot-product recomputation and complete compiler/package/Git provenance are separate reviews.",
            "Actual bytes prove observed lineage together with pinned native bodies; equal bytes alone cannot identify which host pointer supplied them.",
            "Per-operation memory snapshots bracket allocations while the context/module is live; they do not prove exhaustive heap leak freedom.",
            "The checker writes its final observations after Session.close, but does not retain a separate top-level session-close status record.",
            "Host waits overlap event profiles; advance contains nested work. The disjoint nested host bound is checked, but categories must not be added as independent cost.",
            "Absolute steady-clock timestamps from separate processes/jobs are not aligned. Durations describe host runtime queue/staging observations, never physical GPU latency, throughput or speedup.",
            "Tensor byte totals include destination poison and exclude argument/control, module/setup and implicit host copies; argument-block bytes are an ABI inventory, not measured bus traffic.",
            "This reads extracted regular members only, opens no archives and follows no symlinks. No phase acceptance, PyTorch, training, vendor hw_emu, FPGA or silicon claim follows.",
        ]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--packet", type=Path, action="append", required=True)
    parser.add_argument("--selected-scope", action="store_true")
    parser.add_argument("--output", type=Path, required=True, help="fresh JSON path in an existing canonical directory")
    args = parser.parse_args(argv)
    try:
        absolute_name(str(args.output), "output")
        plain_directory(args.output.parent)
        check(not os.path.lexists(args.output), "output already exists")
        for packet in args.packet:
            check(not args.output.is_relative_to(packet), "output must be outside input packet")
    except (OSError, ValueError) as error:
        print(json.dumps({"audit": "p05-independent-dispatch-v1", "outcome": "fail", "phase_acceptance": False, "reason": str(error)}))
        return 2
    try:
        result = audit_packets(args.source_dir, args.packet, args.selected_scope)
    except (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError, IndexError, AttributeError) as error:
        result = {"schema_version": 1, "audit": "p05-independent-dispatch-v1", "outcome": "fail",
                  "phase_acceptance": False, "reason": str(error)}
    encoded = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    try:
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(encoded)
    except OSError as error:
        print(json.dumps({"audit": "p05-independent-dispatch-v1", "outcome": "fail", "phase_acceptance": False, "reason": str(error)}))
        return 2
    print(encoded, end="")
    return 0 if result["outcome"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
