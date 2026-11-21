import hashlib
import json
from pathlib import Path
import platform
import random
import struct
import sys
import torch


def pack16(tensor, column_major=False):
    physical = tensor.t() if column_major else tensor
    values = physical.view(torch.int16).flatten().tolist()
    return struct.pack(f"<{len(values)}h", *values)


def pack32(tensor):
    values = tensor.view(torch.int32).flatten().tolist()
    return struct.pack(f"<{len(values)}i", *values)


def validate(tensor, dtype, shape, strides):
    if type(tensor) is not torch.Tensor:
        raise TypeError("exact Tensor required")
    if tensor.layout != torch.strided or tensor.device.type != "cpu":
        raise ValueError("CPU strided required")
    if tensor.dtype != dtype or tensor.ndim != 2:
        raise ValueError("dtype/rank")
    if tensor.requires_grad or torch.autograd.forward_ad.unpack_dual(tensor).tangent is not None:
        raise ValueError("grad/dual")
    if tensor.is_neg() or tensor.is_conj():
        raise ValueError("lazy value view")
    if tuple(tensor.shape) != shape or tuple(tensor.stride()) != strides:
        raise ValueError("shape/stride")
    if tensor.storage_offset() != 0:
        raise ValueError("offset")


def fails(function):
    try:
        function()
    except Exception as error:
        return {"type": type(error).__name__, "message": str(error)}
    raise AssertionError("expected rejection")


assert torch.__version__ == "2.15.0+cpu"
assert sys.byteorder == "little"
torch.set_num_threads(1)
results = {
    "scope": "host-only PyTorch bit transport; no Vortex, SimX or native arithmetic",
    "python": platform.python_version(),
    "torch": torch.__version__,
    "torch_file": torch.__file__,
    "byteorder": sys.byteorder,
    "numpy_imported": "numpy" in sys.modules,
    "input_transport": [],
    "accepted_signatures": [],
    "output_transport": [],
    "invalid_inputs": {},
    "gotchas": {},
}

for dtype in (torch.float16, torch.bfloat16):
    for name, rows, columns, column_major in (("A", 16, 16, False), ("B", 16, 8, True)):
        count = rows * columns
        hasher = hashlib.sha256()
        calls = 0
        for start in range(0, 65536, count):
            raw = struct.pack(f"<{count}H", *range(start, start + count))
            owner = bytearray(raw)
            flat = torch.frombuffer(owner, dtype=dtype)
            tensor = flat.reshape(columns, rows).t() if column_major else flat.reshape(rows, columns)
            strides = (1, rows) if column_major else (columns, 1)
            validate(tensor, dtype, (rows, columns), strides)
            packed = pack16(tensor, column_major)
            assert packed == raw, (dtype, name, start)
            hasher.update(packed)
            calls += 1
        results["input_transport"].append({
            "dtype": str(dtype), "operand": name, "words": 65536,
            "chunks": calls, "shape": [rows, columns], "strides": list(strides),
            "sha256": hasher.hexdigest(), "outcome": "pass",
        })

for dtype in (torch.float16, torch.bfloat16):
    for m, n, k in ((8, 4, 8), (8, 4, 16), (16, 8, 16)):
        a_raw = struct.pack(f"<{m*k}H", *((i * 541 + 0x7c00) % 65536 for i in range(m*k)))
        b_raw = struct.pack(f"<{k*n}H", *((i * 251 + 0x8000) % 65536 for i in range(k*n)))
        a = torch.frombuffer(bytearray(a_raw), dtype=dtype).reshape(m, k)
        b = torch.frombuffer(bytearray(b_raw), dtype=dtype).reshape(n, k).t()
        validate(a, dtype, (m, k), (k, 1))
        validate(b, dtype, (k, n), (1, k))
        assert pack16(a) == a_raw and pack16(b, True) == b_raw
        out_raw = struct.pack(f"<{m*n}I", *((i * 7919 + 0x7f800001) % (1 << 32) for i in range(m*n)))
        out = torch.frombuffer(bytearray(out_raw), dtype=torch.float32).clone().reshape(m, n)
        assert tuple(out.stride()) == (n, 1) and out.storage_offset() == 0
        assert pack32(out) == out_raw
        results["accepted_signatures"].append({
            "dtype": str(dtype), "m": m, "n": n, "k": k,
            "a_strides": list(a.stride()), "b_strides": list(b.stride()),
            "output_strides": list(out.stride()), "outcome": "pass",
        })

fp32_edges = [
    0, 0x80000000, 1, 0x80000001, 0x007fffff, 0x807fffff,
    0x00800000, 0x80800000, 0x3f800000, 0xbf800000,
    0x7f7fffff, 0xff7fffff, 0x7f800000, 0xff800000,
    0x7f800001, 0xff800001, 0x7fa00001, 0xffa00001,
    0x7fc00000, 0xffc00000, 0x7fc0dead, 0xffc0dead,
    0x7fffffff, 0xffffffff, 0xdeadbeef,
]
rng = random.Random(0xA105)
families = {
    "explicit_edges": fp32_edges,
    "all_high_halves_low_0000": [x << 16 for x in range(65536)],
    "all_high_halves_low_0001": [(x << 16) | 1 for x in range(65536)],
    "all_high_halves_low_ffff": [(x << 16) | 65535 for x in range(65536)],
    "seeded_bits": [rng.getrandbits(32) for _ in range(4096)],
}
for name, words in families.items():
    raw = struct.pack(f"<{len(words)}I", *words)
    buffer = bytearray(raw)
    output = torch.frombuffer(buffer, dtype=torch.float32).clone()
    assert pack32(output) == raw, name
    assert output.storage_offset() == 0 and output.is_contiguous()
    assert not output.requires_grad
    buffer[:] = b"\0" * len(buffer)
    assert pack32(output) == raw, (name, "input-buffer alias")
    output.view(torch.int32)[0] = 0x12345678
    assert buffer == bytearray(len(buffer)), (name, "output alias")
    results["output_transport"].append({
        "family": name, "words": len(words), "sha256": hashlib.sha256(raw).hexdigest(),
        "buffer_independent": True, "outcome": "pass",
    })

base = torch.empty((8, 8), dtype=torch.float16)
invalid = {
    "rank_three": base.reshape(1, 8, 8),
    "row_major_transposed": base.t(),
    "offset": torch.empty(65, dtype=torch.float16)[1:].reshape(8, 8),
    "padded": torch.empty((8, 9), dtype=torch.float16)[:, :8],
    "zero_stride_expand": torch.empty((1, 8), dtype=torch.float16).expand(8, 8),
    "wrong_dtype": torch.empty((8, 8), dtype=torch.float32),
    "gradient": torch.empty((8, 8), dtype=torch.float16, requires_grad=True),
    "negative_lazy_view": torch._neg_view(base),
    "complex_conjugate": torch.empty((8, 8), dtype=torch.complex64).conj(),
    "meta": torch.empty((8, 8), dtype=torch.float16, device="meta"),
    "sparse": base.to_sparse(),
}
for name, tensor in invalid.items():
    results["invalid_inputs"][name] = fails(
        lambda tensor=tensor: validate(tensor, torch.float16, (8, 8), (8, 1)))

with torch.no_grad():
    results["invalid_inputs"]["gradient_under_no_grad"] = fails(
        lambda: validate(invalid["gradient"], torch.float16, (8, 8), (8, 1)))

with torch.autograd.forward_ad.dual_level():
    dual = torch.autograd.forward_ad.make_dual(base, torch.ones_like(base))
    results["invalid_inputs"]["forward_dual"] = fails(
        lambda: validate(dual, torch.float16, (8, 8), (8, 1)))
    cast = dual.view(torch.int16)
    results["gotchas"]["dual_integer_view"] = {
        "input_requires_grad": dual.requires_grad,
        "input_tangent_present": torch.autograd.forward_ad.unpack_dual(dual).tangent is not None,
        "view_tangent_present": torch.autograd.forward_ad.unpack_dual(cast).tangent is not None,
    }

results["gotchas"]["gradient_integer_view"] = {
    "input_requires_grad": invalid["gradient"].requires_grad,
    "view_requires_grad": invalid["gradient"].view(torch.int16).requires_grad,
}
results["gotchas"]["negative_integer_view"] = fails(
    lambda: invalid["negative_lazy_view"].view(torch.int16))

raw = struct.pack("<32H", *range(32))
b = torch.frombuffer(bytearray(raw), dtype=torch.float16).reshape(4, 8).t()
validate(b, torch.float16, (8, 4), (1, 8))
correct = pack16(b, True)
incorrect = pack16(b.contiguous())
assert correct == raw and incorrect != raw
results["gotchas"]["column_major_serialization"] = {
    "physical_order": list(struct.unpack("<32H", correct)),
    "wrong_row_major_order": list(struct.unpack("<32H", incorrect)),
    "transpose_is_view": b.t().untyped_storage().data_ptr() == b.untyped_storage().data_ptr(),
}

large_owner = bytearray(struct.pack("<128H", *range(128)))
larger_storage = torch.frombuffer(large_owner, dtype=torch.float16)[:64].reshape(8, 8)
validate(larger_storage, torch.float16, (8, 8), (8, 1))
assert pack16(larger_storage) == bytes(large_owner[:128])
results["gotchas"]["larger_backing_storage"] = {
    "logical_bytes": larger_storage.numel() * larger_storage.element_size(),
    "storage_bytes": larger_storage.untyped_storage().nbytes(),
    "serialized_bytes": len(pack16(larger_storage)),
    "trailing_storage_not_read": True,
}

results["outcome"] = "pass"
target = Path(__file__).with_suffix(".json")
target.write_text(json.dumps(results, indent=2) + "\n")
print(json.dumps(results, indent=2))
