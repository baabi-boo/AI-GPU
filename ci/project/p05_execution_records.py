# SPDX-License-Identifier: Apache-2.0
"""Independently check installed P05 observations against unchanged native runs.

This is a P05 comparison slice. It does not alter the P03 full-matrix selection
gate, generate expected arithmetic, or infer execution from a successful label.
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re

from p02_matrix_records import require
import p03_execution_records as matmul_records
import p04_execution_records as model_records


POISONS = (0x7FC0DEAD, 0xDEADBEEF)
MATMUL_SELECTION = (
    ("single-dense_boundaries", (8, 4, 8)),
    ("numerical-cross_tile_rounding_positive", (8, 4, 16)),
    ("multi-dense_boundaries", (16, 8, 16)),
)
MODEL_FAMILIES = ("seeded_dense", "negated_dense", "zero", "signed_basis", "split_boundary")
MAX_JSON_BYTES = 16 * 1024 * 1024
OBSERVATION_KEYS = {
    "schema_version", "contract_id", "scope", "binding", "installation", "matmuls",
    "models", "counts", "outcome", "acceptance_claimed",
}
INSTALLATION_KEYS = {
    "python_version", "python_implementation", "executable", "prefix", "base_prefix",
    "package_file", "extension_file", "distribution_version", "build_info", "runtime_libraries",
}
RESOURCE_KEYS = {"before_status", "after_status", "free_before", "used_before", "free_after", "used_after"}


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate P05 JSON field: " + key)
        result[key] = value
    return result


def _noninteger(token):
    raise ValueError("noninteger P05 JSON number: " + token)


def decode_json(raw):
    require(type(raw) is bytes and len(raw) <= MAX_JSON_BYTES, "P05 JSON missing or oversized")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                          parse_float=_noninteger, parse_constant=_noninteger)
    except (UnicodeError, RecursionError, OverflowError) as error:
        raise ValueError("invalid bounded P05 JSON") from error


def _same(actual, expected, message):
    require(json.dumps(actual, sort_keys=True, separators=(",", ":"), allow_nan=False)
            == json.dumps(expected, sort_keys=True, separators=(",", ":"), allow_nan=False), message)


def _fields(value, expected, label):
    require(type(value) is dict and set(value) == expected, "invalid P05 " + label + " fields")


def _uint(value, label):
    require(type(value) is int and 0 <= value <= (1 << 64) - 1, "invalid P05 " + label)


def select_matmul_cases(cases, fmt):
    """Select three frozen P05 comparisons without invoking or changing P03 gates."""
    require(fmt in ("fp16", "bf16"), "unsupported P05 format")
    require(type(cases) is list and len(cases) == 88, "expected all 88 frozen P02 cases")
    require(Counter(case["format"] for case in cases) == {"fp16": 44, "bf16": 44},
            "incomplete frozen P02 format inventory")
    indexed = {case["id"]: case for case in cases}
    require(len(indexed) == len(cases), "duplicate frozen P02 case")
    result = []
    for family, shape in MATMUL_SELECTION:
        name = fmt + "-" + family
        require(name in indexed, "missing fixed P05 comparison: " + name)
        case = indexed[name]
        require(case["format"] == fmt and tuple(case[key] for key in ("m", "n", "k")) == shape,
                "fixed P05 comparison shape differs")
        result.append(case)
    return result


def select_model_cases(cases, fmt):
    expected = [kind + "-" + family for kind in ("fp16", "bf16") for family in MODEL_FAMILIES]
    require(type(cases) is list and [case["id"] for case in cases] == expected,
            "expected the ten frozen P04 model cases in canonical order")
    selected = [case for case in cases if case["format"] == fmt]
    require([case["id"] for case in selected] == [fmt + "-" + family for family in MODEL_FAMILIES],
            "incomplete fixed P05 model comparison")
    return selected


def _status(value, label):
    _same(value, {"validation": "success", "primary": 0, "cleanup": 0, "complete": True},
          "P05 " + label + " is not completed successful cleanup")


def _installation(value, request):
    _fields(value, INSTALLATION_KEYS, "installation")
    version = value["python_version"]
    require(type(version) is list and len(version) == 3
            and all(type(item) is int and item >= 0 for item in version) and version[:2] == [3, 12],
            "installed qualification requires CPython 3.12")
    require(value["python_implementation"] == "CPython" and value["distribution_version"] == "0.1.0",
            "installed package/interpreter version differs")
    prefix = Path(request["expected_prefix"])
    require(value["prefix"] == str(prefix) and type(value["base_prefix"]) is str
            and Path(value["base_prefix"]).is_absolute() and value["base_prefix"] != str(prefix),
            "installed check did not use its clean venv")
    require(value["executable"] == str(prefix / "bin/python"),
            "installed check executable differs from the copied venv interpreter")
    for key in ("executable", "package_file", "extension_file"):
        require(type(value[key]) is str, "invalid installed path: " + key)
        path = Path(value[key])
        require(path.is_absolute() and path.is_relative_to(prefix) and path.resolve(strict=True) == path
                and path.is_file(), "installed path is outside the isolated venv: " + key)
    require(Path(value["package_file"]).name == "__init__.py"
            and Path(value["extension_file"]).parent == Path(value["package_file"]).parent
            and Path(value["extension_file"]).name.startswith("_native.")
            and Path(value["extension_file"]).suffix == ".so", "installed module layout differs")
    binding = request["binding"]
    _same(value["build_info"], {"bundle_sha256": binding["bundle_sha256"],
          "source_sha256": binding["source_sha256"], "binding_api": 1},
          "installed extension immutable pins differ")
    libraries = [str(Path(binding["bundle_root"]) / "lib" / name) for name in (
        "libramulator.so", "libramulator-vortex.so", "libvortex.so", "libsimx.so", "libvortex-simx.so")]
    _same(value["runtime_libraries"], libraries, "installed runtime library paths differ")


def _dispatch(value, case, iteration, binding_id):
    _fields(value, model_records.DISPATCH_KEYS, "matmul dispatch")
    for key in model_records.DISPATCH_NUMBERS:
        _uint(value[key], "dispatch." + key)
    require(value["qualification_id"] == binding_id and value["input_dtype"] == case["format"],
            "installed matmul binding/format differs")
    require(tuple(value[key] for key in ("m", "n", "k")) == tuple(case[key] for key in ("m", "n", "k")),
            "installed matmul shape differs")
    require(value["poison"] == POISONS[iteration]
            and value["wait_calls"] > value["timed_out_waits"], "installed matmul poison/wait differs")
    require(value["profiling_enabled"] is True, "installed matmul profiling is disabled")
    for key in ("event_results", "event_profile_results", "event_profile_queried", "event_profiles"):
        require(type(value[key]) is list and len(value[key]) == 5, "missing installed five-event inventory")
    end = 0
    for index, profile in enumerate(value["event_profiles"]):
        require(type(value["event_results"][index]) is int and value["event_results"][index] == 0
                and type(value["event_profile_results"][index]) is int
                and value["event_profile_results"][index] == 0
                and value["event_profile_queried"][index] is True, "installed event/profile failure")
        _fields(profile, model_records.PROFILE_KEYS, "event profile")
        for key in model_records.PROFILE_KEYS:
            _uint(profile[key], "profile." + key)
        queued, submitted, started, ended = (profile[key] for key in
                                            ("queued_ns", "submit_ns", "start_ns", "end_ns"))
        require(queued <= submitted <= started <= ended and end <= submitted,
                "installed event ordering differs")
        end = ended
    # The unchanged P03 validator below independently checks extents, ABI bytes,
    # addresses, non-overlap and actual launch/transfer counts from these fields.
    return end


def _raw_rows(text, marker):
    require(type(text) is str and len(text.encode("utf-8")) <= MAX_JSON_BYTES,
            "installed raw log is missing or oversized")
    require(not any((ord(char) < 32 and char not in "\t\n\r") or 127 <= ord(char) <= 159 for char in text),
            "installed raw log contains control bytes")
    require(not re.search(r"\b(?:FAILED|FAIL|ERROR|FATAL|ABORTED|MISMATCH)\b|P05_FAILURE|"
                          r"Segmentation fault|runtime error:", text, re.IGNORECASE),
            "installed raw log contains a failure")
    result = []
    for line in text.splitlines():
        if marker.casefold() in line.casefold():
            require(line.startswith(marker + " "), "malformed installed raw observation marker")
            result.append(decode_json(line[len(marker) + 1:].encode("utf-8")))
    return result


def verify_observations(value, request, *, native_matmuls, native_models, model_cases, raw_log):
    """Verify actual installed records and return independently derived counts."""
    _fields(value, OBSERVATION_KEYS, "observation")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1
            and value["contract_id"] == "p05-installed-observations-v1"
            and value["scope"] == "simx-installed-python" and value["outcome"] == "pass"
            and value["acceptance_claimed"] is False, "installed observations did not complete")
    _same(value["binding"], request["binding"], "installed observed binding differs from request")
    _installation(value["installation"], request)
    _same(_raw_rows(raw_log, "P05_MATMUL"), value["matmuls"], "installed matmul file differs from raw log")
    _same(_raw_rows(raw_log, "P05_MODEL"), value["models"], "installed model file differs from raw log")
    require(type(value["matmuls"]) is list and len(value["matmuls"]) == 6
            and type(value["models"]) is list and len(value["models"]) == 10,
            "installed comparison inventory is incomplete")
    raw_sequence = [line.split(" ", 1)[0] for line in raw_log.splitlines()
                    if line.startswith(("P05_MATMUL ", "P05_MODEL "))]
    require(raw_sequence == ["P05_MATMUL"] * 6 + ["P05_MODEL"] * 10,
            "installed raw observation chronology differs from the checker")
    binding = request["binding"]
    observed_matmuls = []
    previous_end = 0
    for case_index, case in enumerate(request["matmul_cases"]):
        translated = []
        for iteration in range(2):
            row = value["matmuls"][case_index * 2 + iteration]
            _fields(row, {"case_id", "iteration", "status", "close_status", "actual_bits", "trace", "resources"},
                    "matmul observation")
            require(row["case_id"] == case["id"] and type(row["iteration"]) is int
                    and row["iteration"] == iteration, "installed matmul membership/order differs")
            _status(row["status"], "matmul completion")
            _status(row["close_status"], "matmul close")
            trace = row["trace"]
            end = _dispatch(trace, case, iteration, binding["qualification_id"])
            require(previous_end <= trace["event_profiles"][0]["queued_ns"],
                    "installed matmul precedes its completed predecessor")
            previous_end = end
            resources = row["resources"]
            _fields(resources, RESOURCE_KEYS, "matmul resources")
            for key, item in resources.items():
                _uint(item, "resources." + key)
            require(resources["before_status"] == resources["after_status"] == 0,
                    "installed matmul memory observation failed")
            dispatch = {key: trace[key] for key in (
                "a_address", "b_address", "d_address", "a_bytes", "b_bytes", "d_bytes", "poison", "argument_bytes")}
            dispatch.update(writes=trace["writes_enqueued"], reads=trace["reads_enqueued"],
                            launches=trace["launches_enqueued"], waits=trace["wait_calls"])
            # This adapter only renames actual observed fields for the unchanged
            # P03 parser; it never supplies missing output, resource or ABI data.
            translated.append({"case_id": row["case_id"], "format": case["format"],
                "m": case["m"], "n": case["n"], "k": case["k"], "iteration": iteration,
                "checked": len(row["actual_bits"]),
                "mismatches": sum(left != right for left, right in zip(row["actual_bits"], case["expected"])),
                "actual_bits": row["actual_bits"], "qualification_id": trace["qualification_id"],
                "dispatch": dispatch, "resources": {**{key: resources[key] for key in
                    ("used_before", "used_after", "free_before", "free_after")},
                    "primary": row["close_status"]["primary"], "cleanup": row["close_status"]["cleanup"]}})
            _same(row["actual_bits"], native_matmuls[case["id"]][iteration]["actual_bits"],
                  "installed matmul raw words differ from unchanged native executable")
        wrapped = "\n".join("P03_RESULT " + json.dumps(row, separators=(",", ":")) for row in translated)
        observed_matmuls.extend(matmul_records.verify_output(
            wrapped + "\nPASSED!\n", case, 2, binding["qualification_id"]))
    observed_models = []
    for case_index, case in enumerate(model_cases):
        records = []
        for iteration in range(2):
            row = value["models"][case_index * 2 + iteration]
            _fields(row, {"case_id", "iteration", "record"}, "model observation")
            require(row["case_id"] == case["id"] and type(row["iteration"]) is int
                    and row["iteration"] == iteration, "installed model membership/order differs")
            records.append(row["record"])
        wrapped = "\n".join("P04_RESULT " + json.dumps(row, separators=(",", ":")) for row in records)
        checked = model_records.verify_output(wrapped + "\nPASSED!\n", case, 2,
            binding["qualification_id"], backend="simx", source_revision=binding["source_revision"],
            fixture_sha256=native_models[case["id"]][0]["fixture_sha256"])
        for iteration, observed in enumerate(checked):
            trace = observed["trace"]
            require(previous_end <= trace["create_begin_ns"],
                    "installed model precedes its completed predecessor")
            previous_end = trace["native"][-1]["dispatch"]["event_profiles"][-1]["end_ns"]
            native = native_models[case["id"]][iteration]["trace"]
            for key in ("hidden_words", "bridge_words", "bridge_bytes", "output_words"):
                _same(trace[key], native[key], "installed/native model differs: " + key)
            for actual_stage, native_stage in zip(trace["native"], native["native"]):
                for key in ("a_bytes", "b_bytes", "output_words"):
                    _same(actual_stage[key], native_stage[key], "installed/native model stage differs: " + key)
        observed_models.extend(checked)
    counts = {"matmul_runs": len(observed_matmuls), "model_runs": len(observed_models),
        "matmul_launches": sum(row["dispatch"]["launches"] for row in observed_matmuls),
        "model_launches": sum(stage["dispatch"]["launches_enqueued"]
                              for row in observed_models for stage in row["trace"]["native"])}
    counts["total_launches"] = counts["matmul_launches"] + counts["model_launches"]
    _same(counts, {"matmul_runs": 6, "model_runs": 10, "matmul_launches": 6,
                  "model_launches": 30, "total_launches": 36}, "installed observed counts differ")
    _same(value["counts"], counts, "installed supplied counts differ from observed dispatch")
    return {"counts": counts, "matmul_words": sum(len(row["actual_bits"]) for row in observed_matmuls),
            "model_hidden_words": sum(len(row["trace"]["hidden_words"]) for row in observed_models),
            "model_bridge_words": sum(len(row["trace"]["bridge_words"]) for row in observed_models),
            "model_output_words": sum(len(row["trace"]["output_words"]) for row in observed_models),
            "event_profile_pairs": counts["total_launches"] * 5}
