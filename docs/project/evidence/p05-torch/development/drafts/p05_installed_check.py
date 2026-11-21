#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Observe the frozen matrix through an isolated, installed vortex-ai package."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib
import importlib.machinery
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import stat
import struct
import sys
import tempfile
import time
import traceback


MAX_REQUEST_BYTES = 1024 * 1024
MATRIX_SECONDS = 300
CLEANUP_SECONDS = 15
WAIT_NS = 100_000_000
TIMEOUT = 7
POISONS = (0x7FC0DEAD, 0xDEADBEEF)
MODEL_FAMILIES = ("seeded_dense", "negated_dense", "zero", "signed_basis", "split_boundary")
MATMUL_SELECTION = (
    ("single-dense_boundaries", (8, 4, 8)),
    ("numerical-cross_tile_rounding_positive", (8, 4, 16)),
    ("multi-dense_boundaries", (16, 8, 16)),
)
LIBRARY_NAMES = (
    "libramulator.so", "libramulator-vortex.so", "libvortex.so",
    "libsimx.so", "libvortex-simx.so",
)
WORD = re.compile(r"[0-9a-f]{8}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
STATUS_KEYS = {"validation", "primary", "cleanup", "complete"}
BINDING_KEYS = {
    "backend", "format", "bundle_root", "bundle_sha256", "source_sha256",
    "qualification_id", "source_revision",
}
REQUEST_KEYS = {
    "schema_version", "contract_id", "binding", "matmul_cases", "model_cases",
    "iterations", "expected_prefix",
}
MODEL_RECORD_KEYS = {
    "schema_version", "model_id", "fixture_id", "fixture_sha256", "source_revision",
    "backend", "iteration", "qualification_id", "clock", "timing_scope", "trace",
}
DISPATCH_NUMBERS = {
    "m", "n", "k", "poison", "a_address", "b_address", "d_address", "a_bytes",
    "b_bytes", "d_bytes", "writes_enqueued", "launches_enqueued", "reads_enqueued",
    "wait_calls", "timed_out_waits",
}
DISPATCH_KEYS = DISPATCH_NUMBERS | {
    "qualification_id", "input_dtype", "argument_bytes", "event_results",
    "profiling_enabled", "event_profiles", "event_profile_results", "event_profile_queried",
}

# ci/project/fixtures/{p02_layout_v1,p02_wmma_numerical_v1}.json cases gain m/n/k,
# then use sorted compact UTF-8 JSON. P04 pins hash little-endian output_words
# from ci/project/fixtures/p04_tiny_mlp_v1.json; no arithmetic is reproduced here.
MATMUL_SHA256 = {
    "fp16-single-dense_boundaries": "0b06de9dc9ac1d6bb33578093a88c1c4475e3639655fa86f91bb57b924c83bb6",
    "fp16-numerical-cross_tile_rounding_positive": "e441a569870ee1b507de830df27e676d3dd8875a7af6aa6bd984d6c515404af1",
    "fp16-multi-dense_boundaries": "305ec67a748f1bb55cc3514c5eceffa81fcb6983f947b78301939e6973237949",
    "bf16-single-dense_boundaries": "877cd59b822bd770a6c25b22ebe82e46468fdb364ab7b548b43fa2ff497a5d08",
    "bf16-numerical-cross_tile_rounding_positive": "1572c52c2062cfdfcfb9af98b8e001b2767420400b1a2c6876fde827f11cd152",
    "bf16-multi-dense_boundaries": "50a5261dc0360e2cfc409ec132aee1e33c3d44781b6681f671e86e35efe3c0e8",
}
MODEL_OUTPUT_SHA256 = {
    "seeded_dense": "7d191acbe3677011c541912bbbb8ff09e7901a3b1d4abe5c5525de4ff5411a91",
    "negated_dense": "3316f4f857b9761bbd260eadbc6b3b24e480c1b91f32a9c7f5c794bfac824966",
    "zero": "5341e6b2646979a70e57653007a1f310169421ec9bdd9f1a5648f75ade005af1",
    "signed_basis": "628313135863818abff9b6cf789e19a78c4e321df743b365b61798ad0b04c2b5",
    "split_boundary": "7932ac18d37e6a8f5cfefa98a0f67e1c221b83c688112047f237f0b3855f9b51",
}
MODEL_FIXTURE_SHA256 = "d22a899827afb3e8c22a528fc6a27fd12ff114ef39caf9ffa0cccd77e849cd03"


class CheckError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise CheckError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def fields(value, keys, label):
    require(type(value) is dict and set(value) == keys, "invalid " + label + " fields")


def uint(value, label):
    require(type(value) is int and 0 <= value <= (1 << 64) - 1, "invalid " + label)
    return value


def words(value, count, label):
    require(type(value) is list and len(value) == count
            and all(type(word) is str and WORD.fullmatch(word) for word in value),
            "invalid " + label + " words")
    return value


def packed(value):
    return b"".join(int(word, 16).to_bytes(4, "little") for word in value)


def output_words(value, count):
    require(type(value) is bytes and len(value) == count * 4, "invalid observed output bytes")
    return [f"{word:08x}" for (word,) in struct.iter_unpack("<I", value)]


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate request field: " + key)
        result[key] = value
    return result


def _integer(token):
    require(len(token) <= 64, "oversized request integer")
    return int(token)


def _noninteger(token):
    raise CheckError("noninteger request number: " + token[:32])


def regular_file(path, label):
    require(path.is_absolute() and path.resolve(strict=True) == path,
            label + " must be an absolute path without symlinks")
    require(stat.S_ISREG(path.stat().st_mode), label + " must be a regular file")
    return path


def read_request(path):
    regular_file(path, "request")
    with path.open("rb") as stream:
        data = stream.read(MAX_REQUEST_BYTES + 1)
    require(len(data) <= MAX_REQUEST_BYTES, "request exceeds its byte limit")
    try:
        result = json.loads(data.decode("utf-8"), object_pairs_hook=_unique, parse_int=_integer,
                            parse_float=_noninteger, parse_constant=_noninteger)
    except (UnicodeError, ValueError, RecursionError, OverflowError) as error:
        raise CheckError("invalid bounded request JSON") from error
    validate_request(result)
    return result


def validate_request(request):
    fields(request, REQUEST_KEYS, "request")
    require(type(request["schema_version"]) is int and request["schema_version"] == 1
            and request["contract_id"] == "p05-installed-request-v1"
            and type(request["iterations"]) is int and request["iterations"] == 2,
            "unsupported installed request contract")
    binding = request["binding"]
    fields(binding, BINDING_KEYS, "binding")
    require(binding["backend"] == "simx" and binding["format"] in ("fp16", "bf16"),
            "unsupported installed native variant")
    for key, pattern in (("bundle_sha256", SHA256), ("source_sha256", SHA256),
                         ("qualification_id", SHA256), ("source_revision", COMMIT)):
        require(type(binding[key]) is str and pattern.fullmatch(binding[key]), "invalid " + key)
    for value, label in ((binding["bundle_root"], "bundle root"),
                         (request["expected_prefix"], "expected prefix")):
        require(type(value) is str and "\x00" not in value and Path(value).is_absolute(),
                "invalid " + label)
        path = Path(value)
        require(path.resolve(strict=True) == path and path.is_dir(),
                label + " must be a canonical existing directory")
    fmt = binding["format"]
    cases = request["matmul_cases"]
    require(type(cases) is list and len(cases) == 3, "expected three frozen matmul cases")
    for case, (family, shape) in zip(cases, MATMUL_SELECTION):
        identifier = fmt + "-" + family
        require(type(case) is dict and case.get("id") == identifier,
                "matmul membership or order differs")
        require(hashlib.sha256(canonical(case)).hexdigest() == MATMUL_SHA256[identifier],
                "matmul request differs from frozen fixture bytes: " + identifier)
        require(tuple(case[key] for key in ("m", "n", "k")) == shape and case["format"] == fmt,
                "matmul geometry differs")
    require(request["model_cases"] == [fmt + "-" + family for family in MODEL_FAMILIES],
            "model membership or order differs")


def inspect_installation(request, api):
    require(sys.flags.isolated == 1 and sys.flags.ignore_environment == 1
            and sys.flags.no_user_site == 1, "installed checker requires python -I")
    require(platform.python_implementation() == "CPython" and sys.version_info[:2] == (3, 12),
            "installed qualification requires CPython 3.12")
    prefix = Path(request["expected_prefix"])
    require(sys.prefix == str(prefix) and sys.base_prefix != sys.prefix,
            "interpreter is outside the requested clean venv")
    native = importlib.import_module("vortex_ai._native")
    require(isinstance(native.__spec__.loader, importlib.machinery.ExtensionFileLoader),
            "installed native module is not a compiled extension")
    paths = {"executable": Path(sys.executable), "package_file": Path(api.__file__),
             "extension_file": Path(native.__file__)}
    for key, path in paths.items():
        regular_file(path, key)
        require(path.is_relative_to(prefix), key + " is outside the isolated venv")
    package_dir = paths["package_file"].parent
    require(paths["package_file"].name == "__init__.py"
            and paths["extension_file"].parent == package_dir
            and any(paths["extension_file"].name == "_native" + suffix
                    for suffix in importlib.machinery.EXTENSION_SUFFIXES),
            "installed package/extension layout differs")
    for name, module in tuple(sys.modules.items()):
        if name == "vortex_ai" or name.startswith("vortex_ai."):
            location = getattr(module, "__file__", None)
            require(type(location) is str and Path(location).parent == package_dir,
                    "loaded package module is outside the installed package: " + name)
            regular_file(Path(location), "loaded package module " + name)
    distribution = importlib.metadata.distribution("vortex-ai")
    require(distribution.version == api.__version__ == "0.1.0"
            and distribution.locate_file("vortex_ai/__init__.py").resolve(strict=True)
            == paths["package_file"], "installed distribution identity differs")
    require(type(api.BINDING_API) is int and api.BINDING_API == 1, "binding API differs")
    binding = request["binding"]
    expected_build = {"binding_api": 1, "bundle_sha256": binding["bundle_sha256"],
                      "source_sha256": binding["source_sha256"]}
    build_info = native.build_info()
    require(canonical(build_info) == canonical(expected_build)
            and canonical(api.build_info()) == canonical(build_info),
            "installed native build pins differ")
    require(tuple(api.fixture_cases()) == tuple(fmt + "-" + family
            for fmt in ("fp16", "bf16") for family in MODEL_FAMILIES),
            "installed native frozen model inventory differs")
    require(os.environ.get("LD_LIBRARY_PATH") == str(Path(binding["bundle_root"]) / "lib")
            and os.environ.get("VORTEX_DRIVER") == "simx"
            and not os.environ.get("LD_PRELOAD") and not os.environ.get("LD_AUDIT"),
            "installed checker was not started with the verified loader environment")
    return {"python_version": list(sys.version_info[:3]),
            "python_implementation": platform.python_implementation(),
            **{key: str(path) for key, path in paths.items()}, "prefix": sys.prefix,
            "base_prefix": sys.base_prefix, "distribution_version": distribution.version,
            "build_info": build_info}


def session_identity(session, request):
    info = dict(session.info)
    fields(info, {"format", "backend", "qualification_id", "source_revision",
                  "bundle_sha256", "source_sha256", "libraries"}, "session identity")
    binding = request["binding"]
    for key in BINDING_KEYS - {"bundle_root"}:
        require(info[key] == binding[key], "native session identity differs: " + key)
    libraries = [str(Path(binding["bundle_root"]) / "lib" / name) for name in LIBRARY_NAMES]
    require(type(info["libraries"]) in (tuple, list) and list(info["libraries"]) == libraries,
            "native session runtime library paths differ")
    for library in libraries:
        regular_file(Path(library), "native runtime library")
    return libraries


def execution(status):
    require(dataclasses.is_dataclass(status) and not isinstance(status, type),
            "execution status is not a dataclass observation")
    value = dataclasses.asdict(status)
    fields(value, STATUS_KEYS, "execution status")
    require(type(value["validation"]) is str and type(value["complete"]) is bool,
            "invalid execution status fields")
    uint(value["primary"], "native primary status")
    uint(value["cleanup"], "native cleanup status")
    return value


def successful(status, owner=None):
    value = execution(status)
    if value != {"validation": "success", "primary": 0, "cleanup": 0, "complete": True}:
        status.raise_for_status(owner)
        raise CheckError("native status did not report completed success: " + canonical(value).decode())
    return value


def timeout_ns(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("installed matrix exceeded its wall-clock deadline")
    return min(WAIT_NS, max(1, int(remaining * 1_000_000_000)))


def wait_matmul(operation, deadline):
    status = operation.status
    while True:
        value = execution(status)
        if value["complete"]:
            successful(status, operation)
            return value
        if (value["validation"] != "success" or value["primary"] not in (0, TIMEOUT)
                or value["cleanup"] != 0):
            status.raise_for_status(operation)
        status = operation.wait(timeout_ns(deadline))


def advance_model(operation, deadline):
    status = operation.status
    while True:
        value = execution(status.execution)
        if status.terminal:
            status.raise_for_status(operation)
            successful(status.execution, operation)
            return
        if (status.status != "in_progress" or value["validation"] != "success"
                or value["primary"] not in (0, TIMEOUT) or value["cleanup"] != 0):
            status.raise_for_status(operation)
        status = operation.advance(timeout_ns(deadline))


class RunState:
    def __init__(self):
        self.session = None
        self.session_closed = False
        self.owners = []
        self.closed = set()

    def retain(self, owner):
        if owner is not None and not any(item is owner for item in self.owners):
            self.owners.append(owner)
        return owner

    def close_owner(self, owner, deadline):
        while True:
            status = owner.close(timeout_ns(deadline))
            value = execution(status)
            if value["complete"]:
                self.closed.add(id(owner))
                return successful(status, owner)
            if (value["validation"] != "success" or value["primary"] not in (0, TIMEOUT)
                    or value["cleanup"] != 0):
                status.raise_for_status(owner)


def memory_info(session):
    result = session.memory_info()
    require(type(result) is tuple and len(result) == 3, "invalid memory observation")
    for value in result:
        uint(value, "memory observation")
    require(result[0] == 0, "native memory observation failed")
    return result


def resources(before, after):
    return {"before_status": before[0], "after_status": after[0],
            "free_before": before[1], "used_before": before[2],
            "free_after": after[1], "used_after": after[2]}


def dispatch(trace, shape, fmt, poison, binding_id):
    fields(trace, DISPATCH_KEYS, "native dispatch")
    for key in DISPATCH_NUMBERS:
        uint(trace[key], "dispatch." + key)
    require(trace["qualification_id"] == binding_id and trace["input_dtype"] == fmt
            and tuple(trace[key] for key in ("m", "n", "k")) == shape
            and trace["poison"] == poison, "native dispatch identity differs")
    m, n, k = shape
    sizes = (m * k * 2, k * n * 2, m * n * 4)
    require(tuple(trace[key] for key in ("a_bytes", "b_bytes", "d_bytes")) == sizes
            and tuple(trace[key] for key in ("writes_enqueued", "launches_enqueued", "reads_enqueued"))
            == (3, 1, 1) and trace["wait_calls"] > trace["timed_out_waits"],
            "native transfer/launch/wait inventory differs")
    addresses = tuple(trace[key] for key in ("a_address", "b_address", "d_address"))
    spans = []
    for address, size in zip(addresses, sizes):
        require(address % 4 == 0 and address <= (1 << 64) - size, "invalid native allocation range")
        spans.append((address, address + size))
    require(all(left[1] <= right[0] or right[1] <= left[0]
                for index, left in enumerate(spans) for right in spans[index + 1:]),
            "native operand allocations overlap")
    expected_args = struct.pack("<8I3Q", 1, 56, 1 if fmt == "fp16" else 2, 0,
                                m, n, k, 0, *addresses).hex()
    require(trace["argument_bytes"] == expected_args, "native argument ABI bytes differ")
    require(trace["profiling_enabled"] is True, "native profiling is disabled")
    for key in ("event_results", "event_profile_results", "event_profile_queried", "event_profiles"):
        require(type(trace[key]) is list and len(trace[key]) == 5, "missing five-event observation")
    end = 0
    for index, profile in enumerate(trace["event_profiles"]):
        require(type(trace["event_results"][index]) is int and trace["event_results"][index] == 0
                and type(trace["event_profile_results"][index]) is int
                and trace["event_profile_results"][index] == 0
                and trace["event_profile_queried"][index] is True, "native event/profile failed")
        fields(profile, {"queued_ns", "submit_ns", "start_ns", "end_ns"}, "native event profile")
        for key, value in profile.items():
            uint(value, "profile." + key)
        queued, submitted, started, ended = (profile[key] for key in
                                            ("queued_ns", "submit_ns", "start_ns", "end_ns"))
        require(queued <= submitted <= started <= ended and end <= submitted,
                "native event profile ordering differs")
        end = ended
    return end


def native_success(value, label, *, complete=True):
    fields(value, STATUS_KEYS, label)
    require(all(type(value[key]) is int and value[key] == 0
                for key in ("validation", "primary", "cleanup"))
            and type(value["complete"]) is bool and (value["complete"] or not complete),
            label + " did not succeed: " + canonical(value).decode())


def check_model(record, model, case_id, iteration, binding):
    fields(record, MODEL_RECORD_KEYS, "native model record")
    expected = {"schema_version": 1, "model_id": "p04-tiny-mlp-v1",
                "fixture_id": "p04-tiny-mlp-fixture-v1", "fixture_sha256": MODEL_FIXTURE_SHA256,
                "source_revision": binding["source_revision"], "backend": binding["backend"],
                "iteration": iteration, "qualification_id": binding["qualification_id"],
                "clock": "std::chrono::steady_clock", "timing_scope": "host_runtime_observations"}
    require(canonical({key: record[key] for key in expected}) == canonical(expected),
            "native model record identity differs")
    trace = record["trace"]
    require(type(trace) is dict and canonical(trace) == canonical(model.trace()),
            "native model record differs from its observed trace")
    require(trace["case_id"] == case_id and trace["input_dtype"] == binding["format"]
            and type(trace["poison"]) is int and trace["poison"] == POISONS[iteration],
            "native model trace identity differs")
    for key in ("hidden_valid", "bridge_attempted", "bridge_valid", "bridge_compared", "assembled",
                "logits_valid", "logits_compared", "owner_closed"):
        require(trace[key] is True, "missing successful model observation: " + key)
    for key, expected_number in (("bridge_status", 0), ("bridge_checked_words", 64),
                                 ("bridge_mismatches", 0), ("output_checked_words", 64),
                                 ("output_mismatches", 0)):
        require(uint(trace[key], key) == expected_number, "model comparison failed: " + key)
    native_success(trace["owner_cleanup"], "native model owner cleanup")
    fields(trace["result"], {"status", "execution", "terminal"}, "native model result")
    require(trace["result"]["status"] == "success" and trace["result"]["terminal"] is True,
            "native model inference did not succeed")
    native_success(trace["result"]["execution"], "native model execution")
    memory = trace["resources"]
    fields(memory, {"before_valid", "after_valid", "before_status", "after_status",
                    "free_before", "used_before", "free_after", "used_after"}, "native model resources")
    require(memory["before_valid"] is True and memory["after_valid"] is True,
            "native model memory observations are incomplete")
    for key in set(memory) - {"before_valid", "after_valid"}:
        uint(memory[key], "model resources." + key)
    require(memory["before_status"] == memory["after_status"] == 0
            and memory["free_before"] == memory["free_after"]
            and memory["used_before"] == memory["used_after"], "native model resources were not restored")
    data = model.output_bytes()
    observed = output_words(data, 64)
    require(hashlib.sha256(data).hexdigest() == MODEL_OUTPUT_SHA256[case_id.split("-", 1)[1]],
            "model output differs from immutable fixture bytes")
    require(observed == words(trace["output_words"], 64, "model output"),
            "model output bytes differ from its native record")
    words(trace["hidden_words"], 128, "model hidden")
    bridge = packed(words(trace["bridge_words"], 64, "model bridge"))
    require(trace["bridge_bytes"] == bridge.hex(), "model bridge bytes differ from its native words")
    stages = trace["native"]
    require(type(stages) is list and len(stages) == 3, "expected three observed native model stages")
    specifications = (("hidden_matmul", (16, 8, 16), (0, 16)),
                      ("output_rows_0_7", (8, 4, 8), (0, 8)),
                      ("output_rows_8_15", (8, 4, 8), (8, 16)))
    assembled = []
    end = 0
    for index, (stage, (identifier, shape, rows)) in enumerate(zip(stages, specifications)):
        require(type(stage) is dict and stage["operation_id"] == identifier
                and type(stage["sequence"]) is int and stage["sequence"] == index
                and (stage["row_begin"], stage["row_end"]) == rows, "model native stage order differs")
        for key in ("submitted", "waited", "trace_valid", "output_valid", "compared", "closed"):
            require(stage[key] is True, "missing native model stage observation: " + key)
        native_success(stage["submission"], "native model stage submission", complete=False)
        native_success(stage["completion"], "native model stage completion")
        native_success(stage["cleanup"], "native model stage cleanup")
        count = shape[0] * shape[1]
        require(uint(stage["checked_words"], "stage compared words") == count
                and uint(stage["mismatches"], "stage mismatches") == 0,
                "native model stage comparison failed")
        actual = words(stage["output_words"], count, "native model stage")
        if index == 0:
            require(actual == trace["hidden_words"], "hidden output differs from its native stage")
        else:
            require(stage["a_bytes"] == bridge[(index - 1) * 128:index * 128].hex(),
                    "native model input does not consume the observed bridge")
            assembled.extend(actual)
        require(end <= stage["dispatch"]["event_profiles"][0]["queued_ns"],
                "native model stage precedes its predecessor")
        end = dispatch(stage["dispatch"], shape, binding["format"], POISONS[iteration],
                       binding["qualification_id"])
    require(assembled == observed, "model output differs from observed native row blocks")
    return end


def emit(marker, value, *, stream=None):
    print(marker + " " + canonical(value).decode("utf-8"), file=stream or sys.stdout, flush=True)


def run_matrix(request, api, installation, state):
    deadline = time.monotonic() + MATRIX_SECONDS
    binding = request["binding"]
    session = state.session = api.Session.open(binding["bundle_root"])
    successful(session.status)
    installation["runtime_libraries"] = session_identity(session, request)
    matmuls, models = [], []
    previous_end = 0
    for case in request["matmul_cases"]:
        shape = tuple(case[key] for key in ("m", "n", "k"))
        m, n, k = shape
        a = api.Tensor(packed(case["a_words"]), dtype=case["format"], shape=(m, k), layout="row_major")
        b = api.Tensor(packed(case["b_words"]), dtype=case["format"], shape=(k, n), layout="column_major")
        for iteration, poison in enumerate(POISONS):
            timeout_ns(deadline)
            require(not session.pending_operations(), "a native owner is still pending before matmul")
            before = memory_info(session)
            operation = state.retain(session.submit(a, b, poison=poison))
            status = wait_matmul(operation, deadline)
            close_status = state.close_owner(operation, deadline)
            after = memory_info(session)
            actual = output_words(operation.output_bytes(), m * n)
            trace = operation.trace()
            row = {"case_id": case["id"], "iteration": iteration, "status": status,
                   "close_status": close_status, "actual_bits": actual, "trace": trace,
                   "resources": resources(before, after)}
            emit("P05_MATMUL", row)
            require(before == after, "native matmul resources were not restored")
            require(actual == case["expected"], "matmul output differs from immutable fixture words")
            end = dispatch(trace, shape, case["format"], poison, binding["qualification_id"])
            require(previous_end <= trace["event_profiles"][0]["queued_ns"],
                    "matmul precedes its completed predecessor")
            previous_end = end
            matmuls.append(row)
    for case_id in request["model_cases"]:
        for iteration, poison in enumerate(POISONS):
            timeout_ns(deadline)
            require(not session.pending_operations(), "a native owner is still pending before model")
            model = state.retain(session.model(case_id, poison=poison))
            advance_model(model, deadline)
            state.close_owner(model, deadline)
            model.status.raise_for_status(model)
            record = model.record(iteration)
            row = {"case_id": case_id, "iteration": iteration, "record": record}
            emit("P05_MODEL", row)
            end = check_model(record, model, case_id, iteration, binding)
            require(previous_end <= record["trace"]["create_begin_ns"],
                    "model precedes its completed predecessor")
            previous_end = end
            models.append(row)
    counts = {"matmul_runs": len(matmuls), "model_runs": len(models),
              "matmul_launches": sum(row["trace"]["launches_enqueued"] for row in matmuls),
              "model_launches": sum(stage["dispatch"]["launches_enqueued"]
                  for row in models for stage in row["record"]["trace"]["native"])}
    counts["total_launches"] = counts["matmul_launches"] + counts["model_launches"]
    require(counts == {"matmul_runs": 6, "model_runs": 10, "matmul_launches": 6,
                       "model_launches": 30, "total_launches": 36}, "observed launch totals differ")
    require(not session.pending_operations(), "native owners remain pending after the matrix")
    timeout_ns(deadline)
    close = session.close()
    if execution(close)["complete"]:
        state.session_closed = True
    successful(close)
    timeout_ns(deadline)
    return {"schema_version": 1, "contract_id": "p05-installed-observations-v1",
            "scope": "simx-installed-python", "binding": dict(binding), "installation": installation,
            "matmuls": matmuls, "models": models, "counts": counts,
            "outcome": "pass", "acceptance_claimed": False}


def retain_failure(state, error):
    if state.session is None:
        state.session = getattr(error, "session", None)
    state.retain(getattr(error, "operation", None))
    if state.session is not None:
        try:
            for owner in state.session.pending_operations():
                state.retain(owner)
        except BaseException as pending_error:
            emit("P05_CLEANUP_ERROR", {"action": "pending_operations", "error": str(pending_error)},
                 stream=sys.stderr)


def cleanup_failure(state):
    deadline = time.monotonic() + CLEANUP_SECONDS
    complete = True
    for owner in state.owners:
        if id(owner) in state.closed:
            continue
        last = None
        error = None
        while time.monotonic() < deadline:
            try:
                last = execution(owner.close(timeout_ns(deadline)))
                if last["complete"]:
                    state.closed.add(id(owner))
                    break
            except BaseException as close_error:
                error = str(close_error)
            time.sleep(min(0.01, max(0, deadline - time.monotonic())))
        closed = id(owner) in state.closed
        complete = complete and closed
        emit("P05_CLEANUP", {"owner": type(owner).__name__, "complete": closed,
                             "last_status": last, "error": error}, stream=sys.stderr)
        try:
            emit("P05_DIAGNOSTIC", {"owner": type(owner).__name__, "trace": owner.trace()},
                 stream=sys.stderr)
        except BaseException as diagnostic_error:
            emit("P05_CLEANUP_ERROR", {"action": "trace", "error": str(diagnostic_error)},
                 stream=sys.stderr)
    if state.session is not None and not state.session_closed:
        try:
            value = execution(state.session.close())
            state.session_closed = value["complete"]
            emit("P05_CLEANUP", {"owner": "Session", "last_status": value}, stream=sys.stderr)
        except BaseException as close_error:
            emit("P05_CLEANUP_ERROR", {"action": "session.close", "error": str(close_error)},
                 stream=sys.stderr)
    return complete and (state.session is None or state.session_closed)


def write_observations(path, value):
    data = canonical(value) + b"\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".p05-observations-", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


# Incomplete owners must survive main() so only the standalone CLI terminates them.
_RETAINED_FAILURES = []


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    state = RunState()
    try:
        request = read_request(Path(args.request))
        output = Path(args.output)
        require(output.is_absolute() and output.parent.resolve(strict=True) == output.parent
                and output.parent.is_dir() and not os.path.lexists(output),
                "observation output must be a new absolute path in a canonical existing directory")
        api = importlib.import_module("vortex_ai")
        installation = inspect_installation(request, api)
        observations = run_matrix(request, api, installation, state)
        write_observations(output, observations)
        return 0
    except BaseException as error:
        traceback.print_exception(error, file=sys.stderr)
        sys.stderr.flush()
        retain_failure(state, error)
        complete = cleanup_failure(state)
        emit("P05_FAILURE", {"error_type": type(error).__name__, "error": str(error),
                             "cleanup_complete": complete}, stream=sys.stderr)
        if not complete:
            _RETAINED_FAILURES.append((state, error))
        return 2


if __name__ == "__main__":
    result = main()
    if _RETAINED_FAILURES:
        emit("P05_FAILURE", {"error": "cleanup remained incomplete after the bounded grace period; "
                             "terminating the failed checker process", "cleanup_complete": False},
             stream=sys.stderr)
        sys.stdout.flush()
        sys.stderr.flush()
        try:
            # Native C stdio can remain buffered independently of Python streams.
            import ctypes
            flush = ctypes.CDLL(None).fflush
            flush.argtypes = [ctypes.c_void_p]
            flush.restype = ctypes.c_int
            flush(None)
        except BaseException:
            pass
        os._exit(2)
    raise SystemExit(result)
