# SPDX-License-Identifier: Apache-2.0
"""Host-only exact-storage overlap proof; no accelerator execution."""
import json
import torch
backing = bytearray(260)
a = torch.frombuffer(backing, dtype=torch.float32, count=32).view(8, 4)
b = torch.frombuffer(backing, dtype=torch.float32, count=32, offset=4).view(8, 4)
print(json.dumps({"scope": "host-only-actual-torch-storage", "torch": str(torch.__version__),
    "shape_a": list(a.shape), "shape_b": list(b.shape),
    "strides_a": list(a.stride()), "strides_b": list(b.stride()),
    "offsets": [a.storage_offset(), b.storage_offset()],
    "storage_bytes": [a.untyped_storage().nbytes(), b.untyped_storage().nbytes()],
    "distinct_pointers": a.untyped_storage().data_ptr() != b.untyped_storage().data_ptr(),
    "pointer_delta": b.untyped_storage().data_ptr() - a.untyped_storage().data_ptr()}))
b[0, 0] = 1.0
assert a[0, 1].item() == 1.0
print("Mutation through second exact-extent storage changed first tensor: confirmed overlap")
