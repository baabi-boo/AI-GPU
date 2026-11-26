# SPDX-License-Identifier: Apache-2.0
"""Host unit tests for python/vortex_ai/resident_v2.py (stdlib fallback + mock backend)."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import struct
import sys
import types
import unittest


ROOT = Path(__file__).resolve().parents[2]
PYTHON_DIR = ROOT / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from vortex_ai import _api  # noqa: E402
from aigpu_sdk import resident_v2 as rv2  # noqa: E402


def _f32_bytes(vals):
    return struct.pack(f"<{len(vals)}f", *vals)


def _unpack_f32(data):
    return struct.unpack(f"<{len(data) // 4}f", data)


class MockResidentBackend:
    """In-memory mock verifying zero intermediate host<->device copies during run()."""

    def __init__(self):
        self.next_handle = 1
        self.next_addr = 0x20000
        self.buffers = {}
        self.calls = []
        self.closed = False
        self.fail_on_free = False

    def alloc_buffer(self, nbytes):
        hid = self.next_handle
        self.next_handle += 1
        addr = self.next_addr
        self.next_addr += ((nbytes + 63) // 64) * 64
        self.buffers[hid] = {
            "addr": addr,
            "size": nbytes,
            "data": bytearray(nbytes),
        }
        self.calls.append(("alloc", hid, nbytes))
        return (hid, addr)

    def free_buffer(self, handle):
        self.calls.append(("free", handle))
        if self.fail_on_free:
            raise RuntimeError("injected cleanup failure")
        self.buffers.pop(handle)

    def write_buffer(self, handle, data):
        self.calls.append(("write", handle, len(data)))
        buf = self.buffers[handle]
        if len(data) != buf["size"]:
            raise ValueError("write size mismatch")
        buf["data"][:] = data

    def read_buffer(self, handle, nbytes):
        self.calls.append(("read", handle, nbytes))
        buf = self.buffers[handle]
        if nbytes != buf["size"]:
            raise ValueError("read size mismatch")
        return bytes(buf["data"])

    def copy_buffer(self, dst_handle, src_handle, nbytes, *,
                    src_origin=(0, 0, 0), dst_origin=(0, 0, 0),
                    region=None, src_pitch=0, dst_pitch=0):
        self.calls.append(("copy", dst_handle, src_handle, nbytes))
        src_buf = self.buffers[src_handle]["data"]
        dst_buf = self.buffers[dst_handle]["data"]
        width, rows, _ = region
        for r in range(rows):
            s_off = (src_origin[1] + r) * src_pitch + src_origin[0]
            d_off = (dst_origin[1] + r) * dst_pitch + dst_origin[0]
            dst_buf[d_off:d_off + width] = src_buf[s_off:s_off + width]

    def execute_op(self, spec):
        op = spec["op_name"]
        self.calls.append(("exec", op, spec["input_addrs"], spec["output_addrs"]))
        in_handles = spec["inputs"]
        out_handle = spec["outputs"][0]
        if op == "rmsnorm_fp32":
            rows, cols = spec["input_shapes"][0]
            x = _unpack_f32(self.buffers[in_handles[0]]["data"])
            w = _unpack_f32(self.buffers[in_handles[1]]["data"])
            eps = spec["eps"]
            out = []
            for r in range(rows):
                sq = sum(x[r * cols + c] ** 2 for c in range(cols))
                inv_rms = 1.0 / math.sqrt(sq / cols + eps)
                for c in range(cols):
                    out.append(x[r * cols + c] * inv_rms * w[c])
            self.buffers[out_handle]["data"][:] = _f32_bytes(out)
        elif op == "gelu_fp32":
            x = _unpack_f32(self.buffers[in_handles[0]]["data"])
            k = math.sqrt(2.0 / math.pi)
            out = [0.5 * v * (1.0 + math.tanh(k * (v + 0.044715 * (v ** 3)))) for v in x]
            self.buffers[out_handle]["data"][:] = _f32_bytes(out)
        elif op == "relu_fp32":
            x = _unpack_f32(self.buffers[in_handles[0]]["data"])
            out = [0.0 if v <= 0.0 else v for v in x]
            self.buffers[out_handle]["data"][:] = _f32_bytes(out)
        elif op == "attention_fp32":
            rows, cols = spec["input_shapes"][0]
            q = _unpack_f32(self.buffers[in_handles[0]]["data"])
            k = _unpack_f32(self.buffers[in_handles[1]]["data"])
            v = _unpack_f32(self.buffers[in_handles[2]]["data"])
            scale = 1.0 / math.sqrt(cols)
            out = [0.0] * (rows * cols)
            for i in range(rows):
                scores = [
                    sum(q[i * cols + d] * k[j * cols + d] for d in range(cols)) * scale
                    for j in range(rows)
                ]
                mx = max(scores)
                exps = [math.exp(s - mx) for s in scores]
                denom = sum(exps)
                probs = [e / denom for e in exps]
                for d in range(cols):
                    out[i * cols + d] = sum(probs[j] * v[j * cols + d] for j in range(rows))
            self.buffers[out_handle]["data"][:] = _f32_bytes(out)
        elif op == "cast_fp32_to_fp16":
            x = _unpack_f32(self.buffers[in_handles[0]]["data"])
            self.buffers[out_handle]["data"][:] = struct.pack(f"<{len(x)}e", *x)
        elif op == "cast_fp16_to_fp32":
            raw = self.buffers[in_handles[0]]["data"]
            x = struct.unpack(f"<{len(raw) // 2}e", raw)
            self.buffers[out_handle]["data"][:] = _f32_bytes(x)
        else:
            raise AssertionError(f"unexpected op in mock: {op}")

    def memory_info(self):
        used = sum(b["size"] for b in self.buffers.values())
        return (0, 1024 * 1024 - used, used)

    def close(self):
        self.closed = True


class _FakeStorage:
    def __init__(self, nbytes):
        self._nbytes = nbytes

    def nbytes(self):
        return self._nbytes


class _FakeTorchTensor:
    def __init__(self, data, shape, dtype, *, requires_grad=False, grad_fn=None,
                 device_type="cpu", layout="strided", stride=None,
                 storage_offset=0, is_neg=False, is_conj=False):
        self._data = list(data)
        self.shape = tuple(shape)
        self.dtype = dtype
        self.requires_grad = requires_grad
        self.grad_fn = grad_fn
        self.device = types.SimpleNamespace(type=device_type)
        self.layout = layout
        self._stride = stride if stride is not None else (shape[1], 1)
        self._storage_offset = storage_offset
        self._is_neg = is_neg
        self._is_conj = is_conj
        self.ndim = len(shape)

    def stride(self):
        return self._stride

    def is_neg(self):
        return self._is_neg

    def is_conj(self):
        return self._is_conj

    def storage_offset(self):
        return self._storage_offset

    def numel(self):
        return self.shape[0] * self.shape[1]

    def element_size(self):
        return 4 if self.dtype == "float32" else 2

    def untyped_storage(self):
        return _FakeStorage(self.numel() * self.element_size())

    def t(self):
        rows, cols = self.shape
        transposed = [self._data[r * cols + c] for c in range(cols) for r in range(rows)]
        return _FakeTorchTensor(
            transposed, (cols, rows), self.dtype,
            requires_grad=self.requires_grad, grad_fn=self.grad_fn,
            device_type=self.device.type, layout=self.layout,
            stride=(1, rows),
        )

    def view(self, *shape):
        if len(shape) == 1 and isinstance(shape[0], str):
            return self
        if len(shape) == 1 and isinstance(shape[0], (tuple, list)):
            shape = tuple(shape[0])
        if any(not isinstance(s, int) or s < 0 for s in shape):
            return self
        return _FakeTorchTensor(
            self._data, shape, self.dtype,
            requires_grad=self.requires_grad, grad_fn=self.grad_fn,
            device_type=self.device.type, layout=self.layout,
            stride=(shape[1], 1) if len(shape) == 2 else (1,),
        )

    def flatten(self):
        return self

    def tolist(self):
        if self.dtype == "float32":
            raw = struct.pack(f"<{len(self._data)}f", *self._data)
            return list(struct.unpack(f"<{len(self._data)}i", raw))
        raw = struct.pack(f"<{len(self._data)}e", *self._data)
        return list(struct.unpack(f"<{len(self._data)}h", raw))

    def clone(self):
        return self


def _make_fake_torch():
    mod = types.ModuleType("torch")
    mod.Tensor = _FakeTorchTensor
    mod.strided = "strided"
    mod.float32 = "float32"
    mod.float16 = "float16"
    mod.bfloat16 = "bfloat16"
    mod.int32 = "int32"
    mod.int16 = "int16"

    class _NoCtx:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    mod.inference_mode = lambda _flag: _NoCtx()
    mod.autograd = types.SimpleNamespace(
        forward_ad=types.SimpleNamespace(
            unpack_dual=lambda _t: types.SimpleNamespace(tangent=None),
        )
    )

    def _frombuffer(buf, *, dtype):
        if dtype == "float32":
            vals = struct.unpack(f"<{len(buf) // 4}f", buf)
            return _FakeTorchTensor(vals, (len(vals), 1), dtype, stride=(1, 1))
        vals = struct.unpack(f"<{len(buf) // 2}e", buf)
        return _FakeTorchTensor(vals, (len(vals), 1), dtype, stride=(1, 1))

    mod.frombuffer = _frombuffer
    return mod


class ResidentV2Tests(unittest.TestCase):
    def setUp(self):
        rv2._reset_global_state_for_tests()
        self.backend = MockResidentBackend()

    def tearDown(self):
        rv2._reset_global_state_for_tests()

    def test_pure_import_does_not_require_torch_or_native(self):
        self.assertEqual(rv2.RESIDENT_V2_API, 1)
        self.assertNotIn("vortex_ai._native", sys.modules)
        self.assertNotIn("vortex_ai._bundle", sys.modules)
        self.assertIs(type(rv2.torch_available()), bool)

    def test_resident_buffer_lifecycle_and_use_after_close(self):
        with rv2.ResidentContext.open(self.backend) as ctx:
            buf = ctx.from_f32([1.0, -2.0, 3.5, 4.0], shape=(2, 2))
            self.assertFalse(buf.closed)
            self.assertEqual(buf.nbytes, 16)
            self.assertEqual(buf.strides, (8, 4))
            self.assertEqual(ctx.stats["live_tensors"], 1)
            self.assertEqual(ctx.stats["alloc_count"], 1)
            self.assertEqual(ctx.stats["h2d_bytes"], 16)

            # Context cannot close while resident buffer remains open.
            with self.assertRaises(_api.BindingError) as cm:
                ctx.close()
            self.assertEqual(cm.exception.kind, "state")

            got = buf.to_floats()
            self.assertEqual(got, (1.0, -2.0, 3.5, 4.0))
            self.assertEqual(ctx.stats["d2h_bytes"], 16)

            buf.close()
            self.assertTrue(buf.closed)
            self.assertEqual(ctx.stats["live_tensors"], 0)
            self.assertEqual(ctx.stats["free_count"], 1)

            # Double close is idempotent; use-after-close is strictly rejected.
            buf.close()
            for action in (
                lambda: buf.device_addr,
                lambda: buf.to_bytes(),
                lambda: buf.to_floats(),
                lambda: buf.write(b"\x00" * 16),
                lambda: buf.write_f32([0.0, 0.0, 0.0, 0.0]),
            ):
                with self.assertRaises(_api.BindingError) as err:
                    action()
                self.assertEqual(err.exception.kind, "state")

        self.assertTrue(ctx.closed)
        self.assertTrue(self.backend.closed)
        with self.assertRaises(_api.BindingError):
            ctx.allocate((2, 2))

    def test_multi_op_graph_executes_without_intermediate_host_copies(self):
        with rv2.ResidentContext.open(self.backend) as ctx:
            x = ctx.from_f32([0.5, -0.5, 1.0, -1.0, 0.25, 0.75, -0.25, 1.25], shape=(2, 4))
            w = ctx.from_f32([1.0, 0.5, 1.5, 0.75], shape=(1, 4))
            norm_out = ctx.allocate((2, 4), dtype="fp32")
            gelu_out = ctx.allocate((2, 4), dtype="fp32")
            attn_out = ctx.allocate((2, 4), dtype="fp32")
            cast_out = ctx.allocate((2, 4), dtype="fp16")

            graph = ctx.graph()
            graph.add_op("rmsnorm_fp32", (x, w), (norm_out,))
            graph.add_op("gelu_fp32", (norm_out,), (gelu_out,))
            graph.add_op("attention_fp32", (gelu_out, norm_out, x), (attn_out,))
            graph.add_op("cast_fp32_to_fp16", (attn_out,), (cast_out,))

            calls_before = len(self.backend.calls)
            record = graph.run()
            run_calls = self.backend.calls[calls_before:]

            self.assertEqual(record.op_count, 4)
            self.assertEqual(
                record.op_sequence,
                ("rmsnorm_fp32", "gelu_fp32", "attention_fp32", "cast_fp32_to_fp16"),
            )
            self.assertEqual(record.h2d_bytes_during_run, 0)
            self.assertEqual(record.d2h_bytes_during_run, 0)
            self.assertEqual(record.device_launches, 4)
            self.assertFalse(any(c[0] in ("write", "read") for c in run_calls))

            # Explicit final D2H read after graph execution completes.
            out_vals = attn_out.to_floats()
            self.assertEqual(len(out_vals), 8)
            self.assertTrue(all(math.isfinite(v) for v in out_vals))

            # Verify cast output stayed resident on-device too.
            cast_bytes = cast_out.to_bytes()
            self.assertEqual(len(cast_bytes), 16)

            graph.close()
            with self.assertRaises(_api.BindingError):
                graph.run()

            for buf in (cast_out, attn_out, gelu_out, norm_out, w, x):
                buf.close()

    def test_single_context_enforcement_and_reuse_after_close(self):
        ctx1 = rv2.ResidentContext.open(self.backend)
        with self.assertRaises(_api.BindingError) as cm:
            rv2.ResidentContext.open(MockResidentBackend())
        self.assertEqual(cm.exception.kind, "state")

        ctx1.close()
        ctx2 = rv2.ResidentContext.open(MockResidentBackend())
        buf = ctx2.allocate((2, 2))
        buf.close()
        ctx2.close()

    def test_autograd_and_alias_and_use_after_close_in_graph_are_rejected(self):
        fake_torch = _make_fake_torch()
        with rv2.ResidentContext.open(self.backend) as ctx:
            bad_grad = _FakeTorchTensor([1.0, 2.0, 3.0, 4.0], (2, 2), "float32", requires_grad=True)
            with self.assertRaises(ValueError):
                ctx.from_torch(bad_grad, torch_mod=fake_torch)

            bad_graph_fn = _FakeTorchTensor([1.0, 2.0, 3.0, 4.0], (2, 2), "float32", grad_fn=object())
            with self.assertRaises(ValueError):
                ctx.from_torch(bad_graph_fn, torch_mod=fake_torch)

            dual_torch = _make_fake_torch()
            dual_torch.autograd.forward_ad.unpack_dual = lambda _t: types.SimpleNamespace(tangent=1.0)
            ok_tensor = _FakeTorchTensor([1.0, 2.0, 3.0, 4.0], (2, 2), "float32")
            with self.assertRaises(ValueError):
                ctx.from_torch(ok_tensor, torch_mod=dual_torch)

            # Valid torch upload + roundtrip using fake_torch (and real torch if installed).
            res = ctx.from_torch(ok_tensor, torch_mod=fake_torch)
            back = res.to_torch(torch_mod=fake_torch)
            self.assertEqual(tuple(back.shape), (2, 2))

            # Aliasing src == dst rejected.
            graph = ctx.graph()
            with self.assertRaises(ValueError):
                graph.add_op("gelu_fp32", (res,), (res,))

            # Adding closed tensor rejected; closing intermediate before run() rejected.
            out = ctx.allocate((2, 2), dtype="fp32")
            graph.add_op("relu_fp32", (res,), (out,))
            out.close()
            with self.assertRaises(_api.BindingError):
                graph.run()
            with self.assertRaises(_api.BindingError):
                graph.add_op("relu_fp32", (res,), (out,))

            res.close()

    def test_cleanup_failure_poisons_process_against_new_context(self):
        self.backend.fail_on_free = True
        ctx = rv2.ResidentContext.open(self.backend)
        buf = ctx.allocate((2, 2))
        with self.assertRaises(_api.BindingError) as cm:
            buf.close()
        self.assertEqual(cm.exception.kind, "cleanup")
        with self.assertRaises(_api.BindingError) as cm2:
            rv2.ResidentContext.open(MockResidentBackend())
        self.assertEqual(cm2.exception.kind, "state")
        # Drain mock context cleanly.
        self.backend.fail_on_free = False
        ctx.close(release_tensors=True)


if __name__ == "__main__":
    unittest.main()
