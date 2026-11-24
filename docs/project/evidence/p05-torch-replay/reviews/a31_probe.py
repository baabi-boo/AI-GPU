#!/usr/bin/env python3
"""Host-only tensor representation probes; never run retained/GPU code."""
import copy
from dataclasses import FrozenInstanceError
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1] / "AI-GPU"
sys.path.insert(0, str(ROOT / "ci/project"))
import p05_torch_records as records
from p05_torch_qualification_test_fixture import raw_log, synthetic
from test_p05_retained_observation_records import denied_live_access, retained_identity

SOURCES = (
    "ci/project/p05_torch_records.py", "ci/project/p05_execution_records.py",
    "ci/project/p05_installed_check.py", "ci/project/p05_replay_installation.py",
    "ci/project/p05_replay_native.py", "ci/project/p05_torch_replay.py",
    "ci/project/p05_qualification_test_fixture.py",
    "ci/project/p05_torch_qualification_test_fixture.py",
    "ci/project/test_p05_retained_observation_records.py",
    "docs/project/evidence/p05-torch/reviews/archive_reader.py",
    "ci/project/fixtures/p02_layout_v1.json", "ci/project/fixtures/p02_wmma_numerical_v1.json",
    "ci/project/fixtures/p04_tiny_mlp_v1.json",
)
WIDTH = {"torch.float16": 2, "torch.bfloat16": 2, "torch.float32": 4, "torch.float64": 8}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def manifest():
    return {name: digest((ROOT / name).read_bytes()) for name in SOURCES}


def elements(tensor):
    raw = bytes.fromhex(tensor["bytes"])
    width = WIDTH[tensor["dtype"]]
    return [raw[pos:pos + width] for row in range(tensor["shape"][0])
            for col in range(tensor["shape"][1])
            for pos in [(tensor["storage_offset"] + row * tensor["strides"][0]
                         + col * tensor["strides"][1]) * width]]


def numbers(tensor):
    kind = tensor["dtype"]
    return [struct.unpack("<f", b"\0\0" + chunk)[0] if kind == "torch.bfloat16"
            else struct.unpack({"torch.float16": "<e", "torch.float32": "<f",
                                "torch.float64": "<d"}[kind], chunk)[0]
            for chunk in elements(tensor)]


def equal_numbers(left, right):
    a, b = numbers(left), numbers(right)
    return len(a) == len(b) and all(x == y or (math.isnan(x) and math.isnan(y)) for x, y in zip(a, b))


def relayout(tensor, *, padding=0, offset=0, column=False):
    original = elements(tensor)
    rows, cols = tensor["shape"]
    width = WIDTH[tensor["dtype"]]
    strides = (1, rows + padding) if column else (cols + padding, 1)
    raw = bytearray(b"\xa5" * ((offset + (rows - 1) * strides[0]
                               + (cols - 1) * strides[1] + 1) * width))
    for i, chunk in enumerate(original):
        row, col = divmod(i, cols)
        pos = (offset + row * strides[0] + col * strides[1]) * width
        raw[pos:pos + width] = chunk
    tensor.update(strides=list(strides), storage_offset=offset, bytes=bytes(raw).hex())


def recode(tensor):
    kind = "torch.float32" if WIDTH[tensor["dtype"]] == 2 else "torch.float64"
    raw = b"".join(struct.pack("<f" if kind == "torch.float32" else "<d", x) for x in numbers(tensor))
    tensor.update(dtype=kind, strides=[tensor["shape"][1], 1], storage_offset=0, bytes=raw.hex())


def tensor_at(value, path):
    group, index, key = path
    return value[group][index][key]


def run():
    before, checks = manifest(), []
    for fmt in ("fp16", "bf16"):
        with tempfile.TemporaryDirectory(prefix="a31-host-only-") as temporary:
            producer = Path(temporary) / "producer"
            original, request, native = synthetic(producer, fmt)
            identity = retained_identity(original, request)
            adapter = Path(original["framework"]["adapter_file"]).read_bytes()
            shutil.rmtree(producer)
            frozen = digest(records.canonical({"request": request, "native": native}))
            identity_snapshot = (identity.request_sha256, identity.installed_files)

            def verify(value, req=None, adapter_bytes=adapter):
                with denied_live_access():
                    return records.verify_retained_observations(
                        value, request if req is None else req, retained_identity=identity,
                        adapter_bytes=adapter_bytes, **native, raw_log=raw_log(value))

            def reject(name, value, message, *, req=None, adapter_bytes=adapter, equivalent=False):
                try:
                    verify(value, req, adapter_bytes)
                except ValueError as error:
                    assert message in str(error), (name, str(error))
                    checks.append({"format": fmt, "probe": name, "rejected": str(error),
                                   "logical_values_preserved": equivalent})
                else:
                    raise AssertionError("ACCEPTED altered representation: " + name)

            control = verify(original)
            assert (control["operator_calls"], control["counts"]["total_launches"],
                    control["event_profile_pairs"], control["framework_result_bytes"]) == (16, 36, 180, 4096)
            checks.append({"format": fmt, "probe": "legitimate_control", "passed": True,
                           "counts": control})
            paths = [("framework_matmuls", i, key) for i in range(6) for key in ("a", "b", "result")]
            paths += [("framework_models", i, "result") for i in range(10)]
            for path in paths:
                for attack in ("padded_rows", "offset_prefix", "opposite_layout", "dtype_reencode"):
                    value = copy.deepcopy(original)
                    tensor = tensor_at(value, path)
                    if attack == "padded_rows":
                        relayout(tensor, padding=3)
                    elif attack == "offset_prefix":
                        relayout(tensor, offset=5, column=path[2] == "b")
                    elif attack == "opposite_layout":
                        relayout(tensor, column=path[2] != "b")
                    else:
                        recode(tensor)
                    assert equal_numbers(tensor_at(original, path), tensor), (fmt, path, attack)
                    assert tensor != tensor_at(original, path)
                    reject("/".join(map(str, path)) + "/" + attack, value, "representation differs", equivalent=True)

            representatives = [paths[0], paths[1], paths[2], paths[-1]]
            for path in representatives:
                for field, changed in (("shape", [1, 1]), ("strides", [0, 1]),
                                       ("storage_offset", True), ("device", "cpu:0"),
                                       ("requires_grad", True), ("requires_grad", 0),
                                       ("dtype", "torch.int32"), ("bytes", "extra"),
                                       ("bytes", "uppercase"), ("bytes", "flip")):
                    value = copy.deepcopy(original)
                    tensor = tensor_at(value, path)
                    if field == "bytes":
                        raw = bytes.fromhex(tensor["bytes"])
                        tensor["bytes"] = (raw + b"\x00").hex() if changed == "extra" else (
                            tensor["bytes"].upper() if changed == "uppercase"
                            else (bytes([raw[0] ^ 1]) + raw[1:]).hex())
                        assert tensor != tensor_at(original, path)
                    else:
                        tensor[field] = changed
                    reject("/".join(map(str, path)) + "/" + field + "/" + str(changed), value,
                           "physical bytes differ" if field == "bytes" else "representation differs")

            value, req = copy.deepcopy(original), copy.deepcopy(request)
            changed_adapter = adapter + b"# coordinated inert replacement\n"
            value["framework"]["adapter_sha256"] = req["framework"]["adapter_sha256"] = digest(changed_adapter)
            reject("coordinated_adapter_raw_parsed_request_and_bytes", value, "installed receipt differs",
                   req=req, adapter_bytes=changed_adapter)
            try:
                identity.installed_files = ()
            except FrozenInstanceError:
                checks.append({"format": fmt, "probe": "frozen_identity", "passed": True})
            else:
                raise AssertionError("retained identity is mutable")
            assert frozen == digest(records.canonical({"request": request, "native": native}))
            assert identity_snapshot == (identity.request_sha256, identity.installed_files)
            verify(original)
    assert before == manifest(), "reviewed source or fixture bytes changed"
    return {"scope": "synthetic retained framework tensor and adapter joins", "sources_sha256": before,
            "source_stability": True, "native_execution": "not_run", "retained_code_executed": False,
            "reference_data_changed": False, "acceptance_claimed": False, "checks": checks,
            "rejections": sum("rejected" in row for row in checks),
            "logical_equivalence_rejections": sum(row.get("logical_values_preserved", False) for row in checks),
            "controls": sum(row.get("passed", False) for row in checks)}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
