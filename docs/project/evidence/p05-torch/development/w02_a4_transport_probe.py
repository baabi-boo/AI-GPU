"""Host-only real Torch transport probe; no native execution or acceptance."""

import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parent
path = ROOT / "drafts/p05_torch_installed_check.py"
spec = importlib.util.spec_from_file_location("host_transport_checker", path)
checker = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = checker
spec.loader.exec_module(checker)

import torch

assert str(torch.__version__) == "2.15.0+cpu"
assert sys.version_info[:3] == (3, 12, 14)
contract_path = ROOT / "drafts/p05_torch_contract.json"
checker.inspect_contract(contract_path, {"framework": {
    "contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest()}})
bits16 = [0, 0x8000, 1, 0x7C00, 0xFC00, 0x7E01, 0x7D55, 0x3555]
bits32 = [0, 0x80000000, 1, 0x7F800000, 0xFF800000, 0x7FC01234, 0x7FA05555, 0x3F800000]
count = 0
for dtype in (torch.float16, torch.bfloat16):
    for m, n, k in ((8, 4, 8), (8, 4, 16), (16, 8, 16)):
        a_bytes = struct.pack("<" + "H" * (m * k), *(bits16 * (m * k // 8)))
        b_bytes = struct.pack("<" + "H" * (k * n), *(bits16 * (k * n // 8)))
        result_bytes = struct.pack("<" + "I" * (m * n), *(bits32 * (m * n // 8)))
        a = checker._input(torch, a_bytes, (m, k), dtype)
        b = checker._input(torch, b_bytes, (k, n), dtype, column=True)
        result = checker._input(torch, result_bytes, (m, n), torch.float32)
        for tensor, data, shape, strides, expected_dtype, column in (
            (a, a_bytes, (m, k), (k, 1), dtype, False),
            (b, b_bytes, (k, n), (1, k), dtype, True),
            (result, result_bytes, (m, n), (n, 1), torch.float32, False),
        ):
            observed = checker.tensor_observation(torch, tensor, shape=shape, strides=strides,
                                                  dtype=expected_dtype, physical_column=column)
            assert observed["bytes"] == data.hex()
            assert observed["requires_grad"] is False
            count += 1
        try:
            checker.tensor_observation(torch, b.contiguous(), shape=(k, n), strides=(1, k), dtype=dtype,
                                       physical_column=True)
        except ValueError:
            pass
        else:
            raise AssertionError("row-major replacement for column-major B was accepted")

print(json.dumps({"scope": "host-real-torch-transport-only", "torch": str(torch.__version__),
    "python": list(sys.version_info[:3]), "tensor_observations": count,
    "layout_rejections": 6, "native_executions": 0, "acceptance_claimed": False}))
