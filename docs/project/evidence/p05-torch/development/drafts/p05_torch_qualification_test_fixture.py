# SPDX-License-Identifier: Apache-2.0
"""Synthetic host records only; no PyTorch or accelerator work executes here."""

import hashlib
import json
from pathlib import Path

import p05_qualification_test_fixture as base_fixture
import p05_torch_records as records


def tensor(data, shape, strides, dtype):
    return {"shape": list(shape), "strides": list(strides), "dtype": dtype, "device": "cpu",
            "storage_offset": 0, "requires_grad": False, "bytes": data.hex()}


def packed(words):
    return b"".join(int(word, 16).to_bytes(4, "little") for word in words)


def synthetic(directory, fmt="fp16"):
    base, native_request, native = base_fixture.synthetic(Path(directory), fmt)
    adapter = Path(base["installation"]["package_file"]).parent / "torch_ops.py"
    adapter.write_bytes(b"# HOST-ONLY MOCK IDENTITY; NEVER IMPORTED OR EXECUTED\n")
    adapter_sha = hashlib.sha256(adapter.read_bytes()).hexdigest()
    request = {"schema_version": 1, "contract_id": "p05-torch-request-v1",
               "base_request": native_request, "framework": {"version": records.TORCH_VERSION,
                   "contract_sha256": "f" * 64, "adapter_sha256": adapter_sha}}
    framework = {"version": records.TORCH_VERSION, "distribution_version": records.TORCH_VERSION,
                 "contract_sha256": "f" * 64, "adapter_file": str(adapter), "adapter_sha256": adapter_sha,
                 "operator_schemas": dict(records.SCHEMAS)}
    value = {"schema_version": 1, "contract_id": "p05-torch-observations-v1",
             "scope": "simx-installed-pytorch", "outcome": "pass", "acceptance_claimed": False,
             "framework": framework, "base_observations": base,
             "framework_matmuls": [], "framework_models": []}
    dtype = "torch.float16" if fmt == "fp16" else "torch.bfloat16"
    for index, row in enumerate(base["matmuls"]):
        case = native_request["matmul_cases"][index // 2]
        m, n, k = (case[key] for key in ("m", "n", "k"))
        value["framework_matmuls"].append({"case_id": row["case_id"], "iteration": row["iteration"],
            "a": tensor(packed(case["a_words"]), (m, k), (k, 1), dtype),
            "b": tensor(packed(case["b_words"]), (k, n), (1, k), dtype),
            "result": tensor(packed(row["actual_bits"]), (m, n), (n, 1), "torch.float32")})
    for row in base["models"]:
        value["framework_models"].append({"case_id": row["case_id"], "iteration": row["iteration"],
            "result": tensor(packed(row["record"]["trace"]["output_words"]),
                             (16, 4), (4, 1), "torch.float32")})
    return value, request, native


def raw_log(value):
    rows = [("P05_TORCH_FRAMEWORK", value["framework"])]
    for key, marker in (("matmuls", "MATMUL"), ("models", "MODEL")):
        for native, framework in zip(value["base_observations"][key], value["framework_" + key]):
            rows.append(("P05_" + marker, native))
            rows.append(("P05_TORCH_" + marker, framework))
    return "".join(marker + " " + json.dumps(value, separators=(",", ":")) + "\n"
                   for marker, value in rows)
