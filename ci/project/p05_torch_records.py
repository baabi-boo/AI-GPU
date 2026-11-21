# SPDX-License-Identifier: Apache-2.0
"""Check framework observations against live installation and native records."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat


TORCH_VERSION = "2.15.0+cpu"
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_REQUEST_BYTES = 1024 * 1024
SCHEMAS = {
    "matmul_v1": "vortex_ai::matmul_v1(Tensor a, Tensor b, int session_token, int poison) -> Tensor",
    "fixed_mlp_v1": "vortex_ai::fixed_mlp_v1(str case_id, int session_token, int poison) -> Tensor",
}
REQUEST_KEYS = {"schema_version", "contract_id", "base_request", "framework"}
FRAMEWORK_REQUEST_KEYS = {"version", "contract_sha256", "adapter_sha256"}
OBSERVATION_KEYS = {
    "schema_version", "contract_id", "scope", "outcome", "acceptance_claimed",
    "framework", "base_observations", "framework_matmuls", "framework_models",
}
FRAMEWORK_KEYS = {
    "version", "distribution_version", "contract_sha256", "adapter_file",
    "adapter_sha256", "operator_schemas",
}
TENSOR_KEYS = {"shape", "strides", "dtype", "device", "storage_offset", "requires_grad", "bytes"}
MARKERS = ("P05_TORCH_FRAMEWORK", "P05_MATMUL", "P05_TORCH_MATMUL", "P05_MODEL", "P05_TORCH_MODEL")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def same(actual, expected, message):
    require(canonical(actual) == canonical(expected), message)


def fields(value, expected, label):
    require(type(value) is dict and set(value) == expected, "invalid framework " + label + " fields")


def _unique(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "duplicate framework JSON field: " + key)
        value[key] = item
    return value


def _integer(token):
    require(len(token) <= 64, "oversized framework JSON integer")
    return int(token)


def _noninteger(token):
    raise ValueError("noninteger framework JSON number: " + token[:32])


def decode_json(raw):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_JSON_BYTES, "framework JSON missing or oversized")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique, parse_int=_integer,
                          parse_float=_noninteger, parse_constant=_noninteger)
    except (UnicodeError, RecursionError, OverflowError) as error:
        raise ValueError("invalid bounded framework JSON") from error


def read_json_file(path, *, limit=MAX_REQUEST_BYTES):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path,
            "framework JSON must use an absolute canonical path")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= limit,
                "framework JSON is not a bounded regular file")
        stream = os.fdopen(descriptor, "rb")
        descriptor = None
        with stream:
            raw = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
    finally:
        if descriptor is not None:
            os.close(descriptor)
    stamp = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    require(stamp(before) == stamp(after) == stamp(path.stat()) and not path.is_symlink()
            and len(raw) == before.st_size, "framework JSON changed during its read")
    return decode_json(raw), raw


def validate_request(request, *, base_validator=None):
    fields(request, REQUEST_KEYS, "request")
    require(type(request["schema_version"]) is int and request["schema_version"] == 1
            and request["contract_id"] == "p05-torch-request-v1", "unsupported framework request contract")
    framework = request["framework"]
    fields(framework, FRAMEWORK_REQUEST_KEYS, "request identity")
    require(framework["version"] == TORCH_VERSION, "framework request version differs")
    for key in ("contract_sha256", "adapter_sha256"):
        require(type(framework[key]) is str and SHA256.fullmatch(framework[key]),
                "invalid framework request " + key)
    if base_validator is None:
        from p05_installed_check import validate_request as base_validator
    try:
        base_validator(request["base_request"])
    except (OSError, RuntimeError, KeyError, TypeError, OverflowError) as error:
        raise ValueError("invalid framework native request: " + str(error)) from error
    return request


def read_request(path, *, base_validator=None):
    request, _ = read_json_file(path)
    return validate_request(request, base_validator=base_validator)


def tensor_record_bytes(value, *, shape, strides, dtype, expected, label):
    fields(value, TENSOR_KEYS, label)
    same({key: value[key] for key in TENSOR_KEYS - {"bytes"}}, {
        "shape": list(shape), "strides": list(strides), "dtype": dtype,
        "device": "cpu", "storage_offset": 0, "requires_grad": False,
    }, "framework " + label + " representation differs")
    require(type(value["bytes"]) is str and value["bytes"] == expected.hex(),
            "framework " + label + " physical bytes differ")


def _framework(value, request, installation):
    fields(value, FRAMEWORK_KEYS, "identity")
    for key in ("version", "distribution_version"):
        require(value[key] == TORCH_VERSION, "observed framework version differs")
    for key in ("contract_sha256", "adapter_sha256"):
        require(value[key] == request["framework"][key], "observed framework " + key + " differs")
    same(value["operator_schemas"], SCHEMAS, "observed custom-operator schemas differ")
    require(type(value["adapter_file"]) is str, "invalid installed adapter path")
    adapter = Path(value["adapter_file"])
    expected = Path(installation["package_file"]).parent / "torch_ops.py"
    require(adapter == expected and adapter.is_absolute() and adapter.resolve(strict=True) == adapter
            and not adapter.is_symlink() and adapter.is_file() and 0 < adapter.stat().st_size <= MAX_REQUEST_BYTES,
            "framework adapter is outside the observed installed package")
    require(hashlib.sha256(adapter.read_bytes()).hexdigest() == value["adapter_sha256"],
            "installed framework adapter bytes differ")


def _raw_observations(raw_log):
    require(type(raw_log) is str and len(raw_log.encode("utf-8")) <= MAX_JSON_BYTES,
            "framework raw log missing or oversized")
    require(not any((ord(char) < 32 and char not in "\t\n\r") or 127 <= ord(char) <= 159
                    for char in raw_log), "framework raw log contains control bytes")
    require(not re.search(r"\b(?:FAILED|FAIL|ERROR|FATAL|ABORTED|MISMATCH)\b|P05_FAILURE|"
                          r"Segmentation fault|runtime error:", raw_log, re.IGNORECASE),
            "framework raw log contains a failure")
    result = {marker: [] for marker in MARKERS}
    sequence = []
    for line in raw_log.splitlines():
        lowered = line.casefold()
        if "p05_torch_" in lowered or any(marker.casefold() in lowered for marker in MARKERS):
            matches = [marker for marker in MARKERS if line.startswith(marker + " ")]
            require(len(matches) == 1, "malformed framework raw observation marker")
            marker = matches[0]
            result[marker].append(decode_json(line[len(marker) + 1:].encode("utf-8")))
            sequence.append(marker)
    expected = ["P05_TORCH_FRAMEWORK"] + [marker for _ in range(6)
               for marker in ("P05_MATMUL", "P05_TORCH_MATMUL")] + [marker for _ in range(10)
               for marker in ("P05_MODEL", "P05_TORCH_MODEL")]
    same(sequence, expected, "framework raw observation chronology differs")
    return result


def _packed_words(words):
    return b"".join(int(word, 16).to_bytes(4, "little") for word in words)


def verify_observations(value, request, *, native_matmuls, native_models, model_cases, raw_log):
    """Reconcile actual returned tensor bytes and unchanged native validation."""
    import p05_execution_records as base_records

    validate_request(request)
    fields(value, OBSERVATION_KEYS, "observation")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1
            and value["contract_id"] == "p05-torch-observations-v1"
            and value["scope"] == "simx-installed-pytorch" and value["outcome"] == "pass"
            and value["acceptance_claimed"] is False, "framework observations did not complete")
    base = value["base_observations"]
    require(type(base) is dict and "installation" in base, "missing native framework observations")
    raw = _raw_observations(raw_log)
    same(raw["P05_TORCH_FRAMEWORK"], [value["framework"]], "framework identity differs from raw log")
    for kind in ("matmuls", "models"):
        same(raw["P05_TORCH_" + ("MATMUL" if kind == "matmuls" else "MODEL")],
             value["framework_" + kind], "framework " + kind + " differ from raw log")
    result = base_records.verify_observations(base, request["base_request"],
        native_matmuls=native_matmuls, native_models=native_models,
        model_cases=model_cases, raw_log=raw_log)
    _framework(value["framework"], request, base["installation"])
    require(type(value["framework_matmuls"]) is list and len(value["framework_matmuls"]) == 6
            and type(value["framework_models"]) is list and len(value["framework_models"]) == 10,
            "framework operator call inventory differs")
    input_bytes = 0
    output_bytes = 0
    fmt = request["base_request"]["binding"]["format"]
    dtype = "torch.float16" if fmt == "fp16" else "torch.bfloat16"
    for index, row in enumerate(value["framework_matmuls"]):
        fields(row, {"case_id", "iteration", "a", "b", "result"}, "matmul observation")
        native = base["matmuls"][index]
        same({key: row[key] for key in ("case_id", "iteration")},
             {key: native[key] for key in ("case_id", "iteration")}, "framework matmul identity differs")
        case = request["base_request"]["matmul_cases"][index // 2]
        m, n, k = (case[key] for key in ("m", "n", "k"))
        a, b = (_packed_words(case[key]) for key in ("a_words", "b_words"))
        out = _packed_words(native["actual_bits"])
        tensor_record_bytes(row["a"], shape=(m, k), strides=(k, 1), dtype=dtype, expected=a, label="A")
        tensor_record_bytes(row["b"], shape=(k, n), strides=(1, k), dtype=dtype, expected=b, label="B")
        tensor_record_bytes(row["result"], shape=(m, n), strides=(n, 1), dtype="torch.float32",
                            expected=out, label="matmul result")
        input_bytes += len(a) + len(b)
        output_bytes += len(out)
    for index, row in enumerate(value["framework_models"]):
        fields(row, {"case_id", "iteration", "result"}, "model observation")
        native = base["models"][index]
        same({key: row[key] for key in ("case_id", "iteration")},
             {key: native[key] for key in ("case_id", "iteration")}, "framework model identity differs")
        out = _packed_words(native["record"]["trace"]["output_words"])
        tensor_record_bytes(row["result"], shape=(16, 4), strides=(4, 1), dtype="torch.float32",
                            expected=out, label="model result")
        output_bytes += len(out)
    return {**result, "framework_version": TORCH_VERSION, "operator_calls": 16,
            "framework_matmul_input_bytes": input_bytes, "framework_result_bytes": output_bytes}
