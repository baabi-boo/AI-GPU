# SPDX-License-Identifier: Apache-2.0
"""Comprehensive unit tests for safetensors I/O, SSA IR, ONNX/FX frontends, fusion, and resident planner."""

from __future__ import annotations

import hashlib
import importlib
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[2]
PYTHON_DIR = ROOT / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from aigpu_sdk import resident_v2 as rv2  # noqa: E402
from aigpu_sdk import safetensors_io as st  # noqa: E402
from aigpu_sdk.compiler import (  # noqa: E402
    CompiledGraph,
    FrontendLoweringError,
    IRValidationError,
    OpKind,
    OpNode,
    TensorSpec,
    analyze_liveness,
    fuse_graph,
    lower_fx_trace_spec,
    lower_onnx_graph,
    lower_torch_fx,
    plan_resident_execution,
    validate_graph,
)


def _unpack_f32(data: bytes) -> tuple[float, ...]:
    return struct.unpack(f"<{len(data) // 4}f", data)


def _pack_f32(vals: list[float]) -> bytes:
    return struct.pack(f"<{len(vals)}f", *vals)


class MockResidentCompilerBackend:
    """In-memory mock ResidentContext backend supporting all ops_v2, copy_rect, and TCU matmul."""

    def __init__(self) -> None:
        self.next_handle = 1
        self.next_addr = 0x40000
        self.buffers: dict[int, dict[str, object]] = {}
        self.calls: list[tuple[object, ...]] = []
        self.closed = False

    def alloc_buffer(self, nbytes: int) -> tuple[int, int]:
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

    def free_buffer(self, handle: int) -> None:
        self.calls.append(("free", handle))
        self.buffers.pop(handle)

    def write_buffer(self, handle: int, data: bytes) -> None:
        self.calls.append(("write", handle, len(data)))
        buf = self.buffers[handle]["data"]
        assert isinstance(buf, bytearray)
        if len(data) != len(buf):
            raise ValueError(f"write size mismatch: {len(data)} != {len(buf)}")
        buf[:] = data

    def read_buffer(self, handle: int, nbytes: int) -> bytes:
        self.calls.append(("read", handle, nbytes))
        buf = self.buffers[handle]["data"]
        assert isinstance(buf, bytearray)
        if nbytes != len(buf):
            raise ValueError(f"read size mismatch: {nbytes} != {len(buf)}")
        return bytes(buf)

    def copy_buffer(
        self,
        dst_handle: int,
        src_handle: int,
        nbytes: int,
        *,
        src_origin: tuple[int, int, int] = (0, 0, 0),
        dst_origin: tuple[int, int, int] = (0, 0, 0),
        region: tuple[int, int, int] | None = None,
        src_pitch: int = 0,
        dst_pitch: int = 0,
    ) -> None:
        self.calls.append(("copy", dst_handle, src_handle, nbytes))
        src_buf = self.buffers[src_handle]["data"]
        dst_buf = self.buffers[dst_handle]["data"]
        assert isinstance(src_buf, bytearray) and isinstance(dst_buf, bytearray)
        assert region is not None
        width, rows, _ = region
        for r in range(rows):
            s_off = (src_origin[1] + r) * src_pitch + src_origin[0]
            d_off = (dst_origin[1] + r) * dst_pitch + dst_origin[0]
            dst_buf[d_off:d_off + width] = src_buf[s_off:s_off + width]

    def execute_op(self, spec: dict[str, object]) -> None:
        op = str(spec["op_name"])
        self.calls.append(("exec", op, spec["input_addrs"], spec["output_addrs"]))
        in_handles = spec["inputs"]
        out_handle = spec["outputs"][0]
        assert isinstance(in_handles, tuple) and isinstance(out_handle, int)
        out_buf = self.buffers[out_handle]["data"]
        assert isinstance(out_buf, bytearray)

        if op == "rmsnorm_fp32":
            rows, cols = spec["input_shapes"][0]  # type: ignore[index]
            x = _unpack_f32(bytes(self.buffers[in_handles[0]]["data"]))  # type: ignore[arg-type]
            w = _unpack_f32(bytes(self.buffers[in_handles[1]]["data"]))  # type: ignore[arg-type]
            eps = float(spec["eps"])  # type: ignore[arg-type]
            out = []
            for r in range(rows):
                sq = sum(x[r * cols + c] ** 2 for c in range(cols))
                inv_rms = 1.0 / math.sqrt(sq / cols + eps)
                for c in range(cols):
                    out.append(x[r * cols + c] * inv_rms * w[c])
            out_buf[:] = _pack_f32(out)
        elif op == "layernorm_fp32":
            rows, cols = spec["input_shapes"][0]  # type: ignore[index]
            x = _unpack_f32(bytes(self.buffers[in_handles[0]]["data"]))  # type: ignore[arg-type]
            g = _unpack_f32(bytes(self.buffers[in_handles[1]]["data"]))  # type: ignore[arg-type]
            b = _unpack_f32(bytes(self.buffers[in_handles[2]]["data"]))  # type: ignore[arg-type]
            eps = float(spec["eps"])  # type: ignore[arg-type]
            out = []
            for r in range(rows):
                row = x[r * cols:(r + 1) * cols]
                mean = sum(row) / cols
                var = sum((v - mean) ** 2 for v in row) / cols
                inv_std = 1.0 / math.sqrt(var + eps)
                for c in range(cols):
                    out.append((row[c] - mean) * inv_std * g[c] + b[c])
            out_buf[:] = _pack_f32(out)
        elif op == "gelu_fp32":
            x = _unpack_f32(bytes(self.buffers[in_handles[0]]["data"]))  # type: ignore[arg-type]
            k = math.sqrt(2.0 / math.pi)
            out = [0.5 * v * (1.0 + math.tanh(k * (v + 0.044715 * (v ** 3)))) for v in x]
            out_buf[:] = _pack_f32(out)
        elif op == "relu_fp32":
            x = _unpack_f32(bytes(self.buffers[in_handles[0]]["data"]))  # type: ignore[arg-type]
            out_buf[:] = _pack_f32([0.0 if v <= 0.0 else v for v in x])
        elif op == "softmax_fp32":
            rows, cols = spec["input_shapes"][0]  # type: ignore[index]
            x = _unpack_f32(bytes(self.buffers[in_handles[0]]["data"]))  # type: ignore[arg-type]
            out = []
            for r in range(rows):
                row = x[r * cols:(r + 1) * cols]
                mx = max(row)
                exps = [math.exp(v - mx) for v in row]
                denom = sum(exps)
                out.extend(e / denom for e in exps)
            out_buf[:] = _pack_f32(out)
        elif op == "attention_fp32":
            rows, cols = spec["input_shapes"][0]  # type: ignore[index]
            q = _unpack_f32(bytes(self.buffers[in_handles[0]]["data"]))  # type: ignore[arg-type]
            k = _unpack_f32(bytes(self.buffers[in_handles[1]]["data"]))  # type: ignore[arg-type]
            v = _unpack_f32(bytes(self.buffers[in_handles[2]]["data"]))  # type: ignore[arg-type]
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
            out_buf[:] = _pack_f32(out)
        elif op == "cast_fp32_to_fp16":
            x = _unpack_f32(bytes(self.buffers[in_handles[0]]["data"]))  # type: ignore[arg-type]
            out_buf[:] = struct.pack(f"<{len(x)}e", *x)
        elif op == "cast_fp16_to_fp32":
            raw = bytes(self.buffers[in_handles[0]]["data"])  # type: ignore[arg-type]
            x = struct.unpack(f"<{len(raw) // 2}e", raw)
            out_buf[:] = _pack_f32(list(x))
        elif op == "cast_fp32_to_bf16":
            x = _unpack_f32(bytes(self.buffers[in_handles[0]]["data"]))  # type: ignore[arg-type]
            out_buf[:] = st.pack_bf16(x)
        elif op == "cast_bf16_to_fp32":
            raw = bytes(self.buffers[in_handles[0]]["data"])  # type: ignore[arg-type]
            out_buf[:] = _pack_f32(list(st.unpack_bf16(raw)))
        elif op == "matmul":
            m, k = spec["input_shapes"][0]  # type: ignore[index]
            kb, n = spec["input_shapes"][1]  # type: ignore[index]
            assert k == kb
            in_dtype = spec["input_dtypes"][0]  # type: ignore[index]
            raw_a = bytes(self.buffers[in_handles[0]]["data"])  # type: ignore[arg-type]
            raw_b = bytes(self.buffers[in_handles[1]]["data"])  # type: ignore[arg-type]
            if in_dtype == "fp16":
                a_vals = struct.unpack(f"<{m * k}e", raw_a)
                b_vals = struct.unpack(f"<{k * n}e", raw_b)
            else:
                a_vals = st.unpack_bf16(raw_a)
                b_vals = st.unpack_bf16(raw_b)
            # A is row_major (m, k); B is column_major (k, n) -> B[r, c] at c*k + r
            out = []
            for r in range(m):
                for c in range(n):
                    out.append(sum(a_vals[r * k + p] * b_vals[c * k + p] for p in range(k)))
            out_buf[:] = _pack_f32(out)
        else:
            raise AssertionError(f"unexpected op in mock backend: {op}")

    def close(self) -> None:
        self.closed = True


def _build_two_layer_llama_onnx_spec(*, seq_len: int = 8, d_model: int = 16, d_ff: int = 16) -> dict:
    """Construct a portable ONNX dict for a 2-layer Llama decoder block with SiLU*Up MLP and residuals."""
    nodes: list[dict] = []
    initializers = [
        {"name": "model.norm.weight", "shape": [1, d_model], "dtype": "fp32"},
    ]
    cur = "x"
    for layer in range(2):
        p = f"l{layer}"
        initializers.extend([
            {"name": f"{p}.rms1_w", "shape": [1, d_model], "dtype": "fp32"},
            {"name": f"{p}.wq", "shape": [d_model, d_model], "dtype": "fp32"},
            {"name": f"{p}.wk", "shape": [d_model, d_model], "dtype": "fp32"},
            {"name": f"{p}.wv", "shape": [d_model, d_model], "dtype": "fp32"},
            {"name": f"{p}.wo", "shape": [d_model, d_model], "dtype": "fp32"},
            {"name": f"{p}.rms2_w", "shape": [1, d_model], "dtype": "fp32"},
            {"name": f"{p}.w_gate", "shape": [d_model, d_ff], "dtype": "fp32"},
            {"name": f"{p}.w_up", "shape": [d_model, d_ff], "dtype": "fp32"},
            {"name": f"{p}.w_down", "shape": [d_ff, d_model], "dtype": "fp32"},
        ])
        nodes.extend([
            {"name": f"{p}_rms1", "op_type": "RMSNormalization", "inputs": [cur, f"{p}.rms1_w"], "outputs": [f"{p}.n1"], "attributes": {"epsilon": 1e-5}},
            {"name": f"{p}_q", "op_type": "MatMul", "inputs": [f"{p}.n1", f"{p}.wq"], "outputs": [f"{p}.q"]},
            {"name": f"{p}_k", "op_type": "MatMul", "inputs": [f"{p}.n1", f"{p}.wk"], "outputs": [f"{p}.k"]},
            {"name": f"{p}_v", "op_type": "MatMul", "inputs": [f"{p}.n1", f"{p}.wv"], "outputs": [f"{p}.v"]},
            {"name": f"{p}_rope_q", "op_type": "RotaryEmbedding", "inputs": [f"{p}.q"], "outputs": [f"{p}.q_rope"]},
            {"name": f"{p}_rope_k", "op_type": "RotaryEmbedding", "inputs": [f"{p}.k"], "outputs": [f"{p}.k_rope"]},
            {"name": f"{p}_attn", "op_type": "Attention", "inputs": [f"{p}.q_rope", f"{p}.k_rope", f"{p}.v"], "outputs": [f"{p}.attn_out"]},
            {"name": f"{p}_oproj", "op_type": "MatMul", "inputs": [f"{p}.attn_out", f"{p}.wo"], "outputs": [f"{p}.o_proj"]},
            {"name": f"{p}_res1", "op_type": "Add", "inputs": [cur, f"{p}.o_proj"], "outputs": [f"{p}.h_mid"]},
            {"name": f"{p}_rms2", "op_type": "RMSNormalization", "inputs": [f"{p}.h_mid", f"{p}.rms2_w"], "outputs": [f"{p}.n2"], "attributes": {"epsilon": 1e-5}},
            {"name": f"{p}_gate", "op_type": "MatMul", "inputs": [f"{p}.n2", f"{p}.w_gate"], "outputs": [f"{p}.gate_lin"]},
            {"name": f"{p}_up", "op_type": "MatMul", "inputs": [f"{p}.n2", f"{p}.w_up"], "outputs": [f"{p}.up_lin"]},
            {"name": f"{p}_silu", "op_type": "Silu", "inputs": [f"{p}.gate_lin"], "outputs": [f"{p}.gate_silu"]},
            {"name": f"{p}_mul", "op_type": "Mul", "inputs": [f"{p}.gate_silu", f"{p}.up_lin"], "outputs": [f"{p}.swiglu_out"]},
            {"name": f"{p}_down", "op_type": "MatMul", "inputs": [f"{p}.swiglu_out", f"{p}.w_down"], "outputs": [f"{p}.ffn_out"]},
            {"name": f"{p}_res2", "op_type": "Add", "inputs": [f"{p}.h_mid", f"{p}.ffn_out"], "outputs": [f"{p}.out"]},
        ])
        cur = f"{p}.out"

    nodes.append({"name": "final_norm", "op_type": "RMSNormalization", "inputs": [cur, "model.norm.weight"], "outputs": ["y"]})
    return {
        "name": "llama_2layer_micro",
        "inputs": [{"name": "x", "shape": [seq_len, d_model], "dtype": "fp32"}],
        "initializers": initializers,
        "outputs": ["y"],
        "nodes": nodes,
    }


class SafetensorsIOTests(unittest.TestCase):
    def test_roundtrip_all_supported_dtypes_and_zero_copy_views(self):
        tensors = {
            "t_f32": st.TensorData("F32", (2, 3), st.pack_f32([1.0, -2.5, 3.25, 0.0, -0.5, 42.0])),
            "t_f16": st.TensorData("F16", (2, 2), st.pack_f16([0.5, -1.5, 2.0, -0.25])),
            "t_bf16": st.TensorData("BF16", (1, 4), st.pack_bf16([1.0, -2.0, 3.5, 0.125])),
            "t_i8": st.TensorData("I8", (4,), st.pack_i8([-128, -1, 0, 127])),
            "t_u8": st.TensorData("U8", (4,), st.pack_u8([0, 1, 128, 255])),
            "t_f8": st.TensorData("F8_E4M3", (2, 2), st.pack_f8_e4m3([0.0, 1.5, -3.0, 448.0])),
        }
        meta = {"model": "test", "version": "1"}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "all_dtypes.safetensors"
            st.write_safetensors(path, tensors, metadata=meta)

            # Deterministic sorted-key serialization check (reversed input dict order produces identical bytes).
            reversed_tensors = {k: tensors[k] for k in reversed(list(tensors.keys()))}
            self.assertEqual(
                st.serialize_safetensors(tensors, metadata=meta),
                st.serialize_safetensors(reversed_tensors, metadata={"version": "1", "model": "test"}),
            )

            with st.open_safetensors(path, use_mmap=True) as sf:
                self.assertEqual(sf.metadata, meta)
                self.assertEqual(sf.keys(), tuple(sorted(tensors.keys())))
                for name, orig in tensors.items():
                    info = sf.info(name)
                    self.assertEqual(info.dtype, orig.dtype)
                    self.assertEqual(info.shape, orig.shape)
                    mv = sf.tensor_view(name)
                    try:
                        self.assertIsInstance(mv, memoryview)
                        self.assertTrue(mv.readonly)
                        self.assertEqual(bytes(mv), bytes(orig.data))
                    finally:
                        mv.release()

                self.assertEqual(sf.tensor_floats("t_i8"), (-128.0, -1.0, 0.0, 127.0))
                self.assertEqual(sf.tensor_floats("t_u8"), (0.0, 1.0, 128.0, 255.0))
                self.assertEqual(sf.tensor_floats("t_f8"), (0.0, 1.5, -3.0, 448.0))
                for got, exp in zip(sf.tensor_floats("t_bf16"), (1.0, -2.0, 3.5, 0.125)):
                    self.assertAlmostEqual(got, exp, places=3)

            loaded, loaded_meta = st.load_safetensors(path)
            self.assertEqual(loaded_meta, meta)
            self.assertEqual(set(loaded.keys()), set(tensors.keys()))
            for name in tensors:
                self.assertEqual(bytes(loaded[name].data), bytes(tensors[name].data))

    def test_malformed_headers_oob_overlap_and_non_monotonic_offsets_rejected(self):
        base = st.serialize_safetensors({
            "a": st.TensorData("F32", (2,), st.pack_f32([1.0, 2.0])),
            "b": st.TensorData("F32", (2,), st.pack_f32([3.0, 4.0])),
        })
        orig_len = struct.unpack_from("<Q", base, 0)[0]
        header_dict = json.loads(base[8:8 + orig_len].decode("utf-8"))
        payload = base[8 + orig_len:]

        def _make_corrupt(hdr_obj: dict, body: bytes = payload) -> bytes:
            raw_hdr = json.dumps(hdr_obj).encode("utf-8")
            return struct.pack("<Q", len(raw_hdr)) + raw_hdr + body

        # 1. Truncated < 8 bytes
        with self.assertRaises(st.SafetensorsError):
            st.open_safetensors(b"\x01\x02\x03")

        # 2. Header length past EOF
        bad_len = struct.pack("<Q", 999999) + b"{}"
        with self.assertRaises(st.SafetensorsError):
            st.open_safetensors(bad_len)

        # 3. Non-monotonic data_offsets (begin > end)
        bad_mono = {
            "a": {"dtype": "F32", "shape": [2], "data_offsets": [8, 0]},
            "b": {"dtype": "F32", "shape": [2], "data_offsets": [8, 16]},
        }
        with self.assertRaises(st.SafetensorsError):
            st.open_safetensors(_make_corrupt(bad_mono))

        # 4. Overlapping data_offsets
        bad_overlap = {
            "a": {"dtype": "F32", "shape": [2], "data_offsets": [0, 8]},
            "b": {"dtype": "F32", "shape": [2], "data_offsets": [4, 12]},
        }
        with self.assertRaises(st.SafetensorsError):
            st.open_safetensors(_make_corrupt(bad_overlap, payload[:12]))

        # 5. Out-of-bounds data_offsets past payload end
        bad_oob = {
            "a": {"dtype": "F32", "shape": [2], "data_offsets": [0, 8]},
            "b": {"dtype": "F32", "shape": [2], "data_offsets": [8, 24]},
        }
        with self.assertRaises(st.SafetensorsError):
            st.open_safetensors(_make_corrupt(bad_oob))

        # 6. Shape byte extent mismatch
        bad_shape = {
            "a": {"dtype": "F32", "shape": [3], "data_offsets": [0, 8]},
            "b": {"dtype": "F32", "shape": [2], "data_offsets": [8, 16]},
        }
        with self.assertRaises(st.SafetensorsError):
            st.open_safetensors(_make_corrupt(bad_shape))

        # 7. Unsupported dtype & non-contiguous trailing bytes
        bad_dtype = dict(header_dict)
        bad_dtype["a"] = {"dtype": "F64", "shape": [1], "data_offsets": [0, 8]}
        with self.assertRaises(st.SafetensorsError):
            st.open_safetensors(_make_corrupt(bad_dtype))
        with self.assertRaises(st.SafetensorsError):
            st.open_safetensors(base + b"\x00\x00\x00\x00")

        # 8. Invalid UTF-8 header & NaN JSON constant rejected
        with self.assertRaises(st.SafetensorsError):
            st.open_safetensors(struct.pack("<Q", 4) + b"\xff\xfe\xfd\xfc" + payload)
        with self.assertRaises(st.SafetensorsError):
            bad_nan = b'{"a":{"dtype":"F32","shape":[2],"data_offsets":[0,8]},"x":NaN}'
            st.open_safetensors(struct.pack("<Q", len(bad_nan)) + bad_nan + payload[:8])

    def test_deterministic_micro_llama_checkpoint_sha256_stability(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p1 = Path(tmpdir) / "llama1.safetensors"
            p2 = Path(tmpdir) / "llama2.safetensors"
            st.make_deterministic_micro_llama_safetensors(p1)
            st.make_deterministic_micro_llama_safetensors(p2)

            b1 = p1.read_bytes()
            b2 = p2.read_bytes()
            self.assertEqual(b1, b2)
            sha1 = hashlib.sha256(b1).hexdigest()
            sha2 = hashlib.sha256(b2).hexdigest()
            self.assertEqual(sha1, sha2)

            tensors, meta = st.load_safetensors(p1)
            self.assertEqual(meta["architecture"], "llama_micro")
            self.assertEqual(meta["num_hidden_layers"], "2")
            self.assertIn("model.layers.0.self_attn.q_proj.weight", tensors)
            self.assertIn("model.layers.1.mlp.gate_proj.weight", tensors)
            self.assertIn("model.layers.1.mlp.up_proj.weight", tensors)
            self.assertIn("model.layers.1.mlp.down_proj.weight", tensors)
            self.assertEqual(len(tensors), 1 + 2 * 9 + 2)


class IRAndFrontendTests(unittest.TestCase):
    def test_ir_validator_rejects_cycles_unresolved_inputs_and_shape_mismatches(self):
        tensors = {
            "x": TensorSpec("x", (8, 16), "fp32", role="input"),
            "w": TensorSpec("w", (16, 16), "fp32", role="weight"),
            "y": TensorSpec("y", (8, 16), "fp32", role="output"),
        }
        # Cycle / use-before-def: node uses y before defining it
        with self.assertRaises(IRValidationError):
            CompiledGraph.create(
                name="cyclic",
                tensors={**tensors, "z": TensorSpec("z", (8, 16), "fp32")},
                inputs=("x",),
                weights=("w",),
                outputs=("y",),
                nodes=(
                    OpNode("n1", OpKind.RELU, ("z",), ("y",)),
                    OpNode("n2", OpKind.RELU, ("y",), ("z",)),
                ),
            )

        # Unresolved input
        with self.assertRaises(IRValidationError):
            CompiledGraph.create(
                name="unresolved",
                tensors=tensors,
                inputs=("x",),
                weights=("w",),
                outputs=("y",),
                nodes=(OpNode("n1", OpKind.RELU, ("missing_tensor",), ("y",)),),
            )

        # MatMul inner dimension mismatch
        with self.assertRaises(IRValidationError):
            CompiledGraph.create(
                name="bad_matmul",
                tensors={
                    "x": TensorSpec("x", (8, 16), "fp32", role="input"),
                    "w": TensorSpec("w", (8, 16), "fp32", role="weight"),
                    "y": TensorSpec("y", (8, 16), "fp32", role="output"),
                },
                inputs=("x",),
                weights=("w",),
                outputs=("y",),
                nodes=(OpNode("mm", OpKind.MATMUL, ("x", "w"), ("y",)),),
            )

        # Duplicate SSA output definition
        with self.assertRaises(IRValidationError):
            CompiledGraph.create(
                name="ssa_dup",
                tensors=tensors,
                inputs=("x",),
                weights=("w",),
                outputs=("y",),
                nodes=(
                    OpNode("n1", OpKind.RELU, ("x",), ("y",)),
                    OpNode("n2", OpKind.GELU, ("x",), ("y",)),
                ),
            )

    def test_onnx_lowering_toposort_and_operators(self):
        # Deliberately put Add and Gelu out of topological order to exercise toposort.
        onnx_spec = {
            "name": "unordered_transformer_slice",
            "inputs": [{"name": "x", "shape": [8, 16], "dtype": "fp32"}],
            "initializers": [
                {"name": "rms_w", "shape": [1, 16], "dtype": "fp32"},
                {"name": "w_proj", "shape": [16, 16], "dtype": "fp32"},
                {"name": "gamma", "shape": [1, 16], "dtype": "fp32"},
                {"name": "beta", "shape": [1, 16], "dtype": "fp32"},
            ],
            "outputs": ["out"],
            "nodes": [
                {"name": "ln", "op_type": "LayerNormalization", "inputs": ["act", "gamma", "beta"], "outputs": ["ln_out"]},
                {"name": "res", "op_type": "Add", "inputs": ["x", "ln_out"], "outputs": ["res_out"]},
                {"name": "cast16", "op_type": "Cast", "inputs": ["res_out"], "outputs": ["out"], "attributes": {"to": 10}},
                {"name": "mm", "op_type": "Gemm", "inputs": ["norm", "w_proj"], "outputs": ["proj"], "attributes": {"transB": 1}},
                {"name": "gelu", "op_type": "Gelu", "inputs": ["proj"], "outputs": ["act"]},
                {"name": "rms", "op_type": "RMSNormalization", "inputs": ["x", "rms_w"], "outputs": ["norm"]},
            ],
        }
        ir = lower_onnx_graph(onnx_spec)
        validate_graph(ir)
        self.assertEqual(
            [n.op for n in ir.nodes],
            [OpKind.RMSNORM, OpKind.MATMUL, OpKind.GELU, OpKind.LAYERNORM, OpKind.RESIDUAL_ADD, OpKind.CAST],
        )
        self.assertEqual(ir.tensors["out"].dtype, "fp16")
        self.assertEqual(ir.tensors["out"].shape, (8, 16))

        # Cycle in ONNX graph must raise FrontendLoweringError.
        cyclic = {
            "name": "bad_cycle",
            "inputs": [{"name": "x", "shape": [4, 4], "dtype": "fp32"}],
            "outputs": ["b"],
            "nodes": [
                {"name": "n1", "op_type": "Relu", "inputs": ["b"], "outputs": ["a"]},
                {"name": "n2", "op_type": "Relu", "inputs": ["a"], "outputs": ["b"]},
            ],
        }
        with self.assertRaises(FrontendLoweringError):
            lower_onnx_graph(cyclic)

    def test_fx_portable_trace_spec_and_optional_live_torch_fx_lowering(self):
        # 1. Always verify pure-Python portable FX trace spec (0 skips in clean CPython).
        fx_spec = {
            "name": "MiniLlamaMLP",
            "modules": {
                "norm": {"type": "nn.RMSNorm", "weight_shape": [16], "dtype": "fp32", "eps": 1e-5},
                "gate_proj": {"type": "nn.Linear", "weight_shape": [16, 16], "dtype": "fp32"},
                "up_proj": {"type": "nn.Linear", "weight_shape": [16, 16], "dtype": "fp32"},
                "down_proj": {"type": "nn.Linear", "weight_shape": [16, 16], "dtype": "fp32"},
            },
            "nodes": [
                {"op": "placeholder", "name": "x", "target": "x", "args": [], "meta": {"shape": [8, 16], "dtype": "fp32"}},
                {"op": "call_module", "name": "n", "target": "norm", "args": ["x"]},
                {"op": "call_module", "name": "g", "target": "gate_proj", "args": ["n"]},
                {"op": "call_module", "name": "u", "target": "up_proj", "args": ["n"]},
                {"op": "call_function", "name": "gs", "target": "torch.nn.functional.silu", "args": ["g"]},
                {"op": "call_function", "name": "sw", "target": "operator.mul", "args": ["gs", "u"]},
                {"op": "call_module", "name": "d", "target": "down_proj", "args": ["sw"]},
                {"op": "call_function", "name": "y", "target": "torch.add", "args": ["x", "d"]},
                {"op": "output", "name": "output", "target": "output", "args": ["y"]},
            ],
        }
        ir = lower_fx_trace_spec(fx_spec)
        validate_graph(ir)
        self.assertEqual(
            [n.op for n in ir.nodes],
            [OpKind.RMSNORM, OpKind.LINEAR, OpKind.LINEAR, OpKind.SILU, OpKind.MUL, OpKind.LINEAR, OpKind.RESIDUAL_ADD],
        )

        # 2. Verify live GraphModule object lowering: use real torch.fx if installed,
        #    or a strict GraphModule-protocol test double if torch is absent (zero unittest.skip!).
        try:
            torch = importlib.import_module("torch")
            torch_fx = importlib.import_module("torch.fx")
            has_real_torch = hasattr(torch, "nn") and hasattr(torch_fx, "symbolic_trace")
        except ImportError:
            torch = None
            has_real_torch = False

        if has_real_torch:
            class TinyMod(torch.nn.Module):
                def __init__(self) -> None:
                    super().__init__()
                    self.fc1 = torch.nn.Linear(16, 16, bias=False)
                    self.fc2 = torch.nn.Linear(16, 16, bias=False)

                def forward(self, x):
                    h = torch.nn.functional.silu(self.fc1(x)) * self.fc2(x)
                    return x + h

            gm = torch_fx.symbolic_trace(TinyMod())
            ir_live = lower_torch_fx(gm, example_inputs={"x": ((8, 16), "fp32")})
            validate_graph(ir_live)
            fused_live, rep_live = fuse_graph(ir_live)
            self.assertEqual(rep_live.swiglu_fusions, 1)
            self.assertIn(OpKind.SWIGLU, [n.op for n in fused_live.nodes])
        else:
            # Structural GraphModule protocol test verifying the exact AST walker used for torch.fx.GraphModule.
            class _LinearStub:
                def __init__(self, out_f: int, in_f: int) -> None:
                    self.weight = types.SimpleNamespace(shape=(out_f, in_f), dtype="torch.float32")
                    self.bias = None

            _LinearStub.__name__ = "Linear"

            class _FakeGraphModule:
                def __init__(self) -> None:
                    n_x = types.SimpleNamespace(op="placeholder", name="x", target="x", args=(), kwargs={},
                                                meta={"tensor_meta": types.SimpleNamespace(shape=(8, 16), dtype="torch.float32")})
                    n_fc1 = types.SimpleNamespace(op="call_module", name="fc1_out", target="fc1", args=(n_x,), kwargs={}, meta={})
                    n_fc2 = types.SimpleNamespace(op="call_module", name="fc2_out", target="fc2", args=(n_x,), kwargs={}, meta={})
                    n_silu = types.SimpleNamespace(op="call_function", name="act", target="torch.nn.functional.silu", args=(n_fc1,), kwargs={}, meta={})
                    n_mul = types.SimpleNamespace(op="call_function", name="swiglu", target="operator.mul", args=(n_silu, n_fc2), kwargs={}, meta={})
                    n_add = types.SimpleNamespace(op="call_function", name="res", target="operator.add", args=(n_x, n_mul), kwargs={}, meta={})
                    n_out = types.SimpleNamespace(op="output", name="output", target="output", args=(n_add,), kwargs={}, meta={})
                    self.graph = types.SimpleNamespace(nodes=[n_x, n_fc1, n_fc2, n_silu, n_mul, n_add, n_out])
                    self._mods = {"": self, "fc1": _LinearStub(16, 16), "fc2": _LinearStub(16, 16)}

                def named_modules(self):
                    return list(self._mods.items())

            ir_gm = lower_torch_fx(_FakeGraphModule())
            validate_graph(ir_gm)
            fused_gm, rep_gm = fuse_graph(ir_gm)
            self.assertEqual(rep_gm.swiglu_fusions, 1)
            self.assertIn(OpKind.SWIGLU, [n.op for n in fused_gm.nodes])

    def test_fusion_pass_swiglu_residual_and_rmsnorm_cast(self):
        onnx_spec = {
            "name": "fusable_block",
            "inputs": [{"name": "x", "shape": [8, 16], "dtype": "fp32"}],
            "initializers": [
                {"name": "rms_w", "shape": [1, 16], "dtype": "fp32"},
                {"name": "w_gate", "shape": [16, 16], "dtype": "fp16"},
                {"name": "w_up", "shape": [16, 16], "dtype": "fp16"},
                {"name": "w_down", "shape": [16, 16], "dtype": "fp16"},
                {"name": "w_out", "shape": [16, 16], "dtype": "fp32"},
            ],
            "outputs": ["y"],
            "nodes": [
                {"name": "rms", "op_type": "RMSNormalization", "inputs": ["x", "rms_w"], "outputs": ["n"]},
                {"name": "cast_in", "op_type": "Cast", "inputs": ["n"], "outputs": ["n_f16"], "attributes": {"to": "fp16"}},
                {"name": "gate", "op_type": "MatMul", "inputs": ["n_f16", "w_gate"], "outputs": ["g"]},
                {"name": "up", "op_type": "MatMul", "inputs": ["n_f16", "w_up"], "outputs": ["u"]},
                {"name": "silu", "op_type": "Silu", "inputs": ["g"], "outputs": ["gs"]},
                {"name": "mul", "op_type": "Mul", "inputs": ["gs", "u"], "outputs": ["sw"]},
                {"name": "down", "op_type": "MatMul", "inputs": ["sw", "w_down"], "outputs": ["d_f16"]},
                {"name": "cast_out", "op_type": "Cast", "inputs": ["d_f16"], "outputs": ["d_f32"], "attributes": {"to": "fp32"}},
                {"name": "proj", "op_type": "MatMul", "inputs": ["d_f32", "w_out"], "outputs": ["p"]},
                {"name": "add", "op_type": "Add", "inputs": ["x", "p"], "outputs": ["y"]},
            ],
        }
        raw_ir = lower_onnx_graph(onnx_spec)
        fused_ir, report = fuse_graph(raw_ir)
        validate_graph(fused_ir)

        self.assertEqual(report.swiglu_fusions, 1)
        self.assertEqual(report.residual_fusions, 1)
        self.assertEqual(report.rmsnorm_cast_fusions, 1)
        self.assertEqual(report.total_fusions, 3)
        self.assertEqual(report.original_node_count, 10)
        self.assertEqual(report.fused_node_count, 7)

        ops = [n.op for n in fused_ir.nodes]
        self.assertIn(OpKind.SWIGLU, ops)
        self.assertNotIn(OpKind.SILU, ops)
        self.assertNotIn(OpKind.MUL, ops)
        self.assertNotIn(OpKind.RESIDUAL_ADD, ops)

        fused_rmsnorm = [n for n in fused_ir.nodes if n.op is OpKind.RMSNORM][0]
        self.assertEqual(fused_rmsnorm.attrs["cast_epilogue_dtype"], "fp16")
        fused_proj = [n for n in fused_ir.nodes if n.attrs.get("fused_residual")][0]
        self.assertEqual(len(fused_proj.inputs), 3)
        self.assertEqual(fused_proj.outputs, ("y",))


class PlannerAndResidentExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        rv2._reset_global_state_for_tests()
        self.backend = MockResidentCompilerBackend()

    def tearDown(self) -> None:
        rv2._reset_global_state_for_tests()

    def test_two_layer_llama_liveness_pool_savings_and_conflict_freedom(self):
        raw_graph = lower_onnx_graph(_build_two_layer_llama_onnx_spec(seq_len=8, d_model=16, d_ff=16))
        fused_graph, report = fuse_graph(raw_graph)
        # 2 layers * (SwiGLU + 2 residual additions) = 2 swiglu + 4 residual fusions
        self.assertEqual(report.swiglu_fusions, 2)
        self.assertEqual(report.residual_fusions, 4)

        plan = plan_resident_execution(fused_graph, alignment=64)
        self.assertEqual(plan.intermediate_host_copy_bytes, 0)
        self.assertGreater(plan.naive_bytes, 0)
        self.assertLess(plan.pooled_bytes, plan.naive_bytes)
        self.assertGreater(plan.memory_savings_pct, 50.0)

        # Verify no two tensors sharing any MemorySlot have overlapping closed [first_def, last_use] intervals.
        for slot in plan.slots:
            for i, name_a in enumerate(slot.assigned_tensors):
                lt_a = plan.lifetimes[name_a]
                for name_b in slot.assigned_tensors[i + 1:]:
                    lt_b = plan.lifetimes[name_b]
                    self.assertTrue(
                        lt_a.last_use < lt_b.first_def or lt_b.last_use < lt_a.first_def,
                        f"slot {slot.slot_id} conflict: {name_a} [{lt_a.first_def},{lt_a.last_use}] vs "
                        f"{name_b} [{lt_b.first_def},{lt_b.last_use}]",
                    )

        # Verify every step has pairwise-disjoint input/output slots.
        for step in plan.steps:
            self.assertTrue(
                set(step.input_slots).isdisjoint(set(step.output_slots)),
                f"step {step.node_name} aliases input slot {step.input_slots} with output slot {step.output_slots}",
            )

        # Verify executing the full 2-layer Llama graph through ResidentContext uses pooled slots
        # and transfers ZERO intermediate host<->device bytes during graph.run().
        x_vals = [0.05 * ((i % 7) - 3) for i in range(8 * 16)]
        host_weights = {}
        for wname in fused_graph.weights:
            spec = fused_graph.tensors[wname]
            if "rms" in wname or "norm" in wname:
                host_weights[wname] = [1.0] * spec.numel
            else:
                host_weights[wname] = [0.02 * (((i % 5) - 2)) for i in range(spec.numel)]

        with rv2.ResidentContext.open(self.backend) as ctx:
            results, record, allocated = plan.execute(
                ctx,
                host_inputs={"x": x_vals},
                host_weights=host_weights,
            )
            self.assertEqual(record.h2d_bytes_during_run, 0)
            self.assertEqual(record.d2h_bytes_during_run, 0)
            self.assertGreaterEqual(record.op_count, len(plan.steps))
            self.assertGreater(record.device_launches, 0)
            out_vals = results["y"]
            self.assertEqual(len(out_vals), 8 * 16)
            self.assertTrue(all(math.isfinite(v) for v in out_vals))  # type: ignore[arg-type]

            for buf in reversed(allocated):
                buf.close()

    def test_end_to_end_safetensors_micro_llama_compile_and_execute_resident(self):
        # Load real generated micro-Llama .safetensors weights, compile fused 2-layer graph,
        # pack into tiled FP16 TCU ResidentGraph, and execute with zero intermediate host copies.
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt = Path(tmpdir) / "micro_llama.safetensors"
            st.make_deterministic_micro_llama_safetensors(ckpt)
            loaded, meta = st.load_safetensors(ckpt)
            self.assertEqual(int(meta["num_hidden_layers"]), 2)

            # Build a fused 2-layer graph whose linear weights consume the real FP16 safetensors weights.
            tensors: dict[str, TensorSpec] = {
                "x": TensorSpec("x", (8, 16), "fp32", role="input"),
                "final_norm_w": TensorSpec("final_norm_w", (1, 16), "fp32", role="weight"),
                "y": TensorSpec("y", (8, 16), "fp32", role="output"),
            }
            host_weights: dict[str, bytes | list[float]] = {
                "final_norm_w": list(st.decode_tensor_floats("F32", loaded["model.norm.weight"].data)),
            }
            nodes: list[OpNode] = []
            cur = "x"

            def _to_col_major_f16(raw_f16: bytes, rows: int, cols: int) -> bytes:
                vals = struct.unpack(f"<{rows * cols}e", raw_f16)
                col_major = [vals[r * cols + c] for c in range(cols) for r in range(rows)]
                return struct.pack(f"<{rows * cols}e", *col_major)

            for layer in range(2):
                p = f"model.layers.{layer}"
                rms1_w = f"l{layer}_rms1_w"
                wq_w = f"l{layer}_wq"
                wk_w = f"l{layer}_wk"
                wv_w = f"l{layer}_wv"
                wo_w = f"l{layer}_wo"
                tensors[rms1_w] = TensorSpec(rms1_w, (1, 16), "fp32", role="weight")
                tensors[wq_w] = TensorSpec(wq_w, (16, 16), "fp16", layout="column_major", role="weight")
                tensors[wk_w] = TensorSpec(wk_w, (16, 16), "fp16", layout="column_major", role="weight")
                tensors[wv_w] = TensorSpec(wv_w, (16, 16), "fp16", layout="column_major", role="weight")
                tensors[wo_w] = TensorSpec(wo_w, (16, 16), "fp16", layout="column_major", role="weight")

                host_weights[rms1_w] = list(st.decode_tensor_floats("F32", loaded[f"{p}.input_layernorm.weight"].data))
                host_weights[wq_w] = _to_col_major_f16(loaded[f"{p}.self_attn.q_proj.weight"].data, 16, 16)
                host_weights[wk_w] = _to_col_major_f16(loaded[f"{p}.self_attn.k_proj.weight"].data, 16, 16)
                host_weights[wv_w] = _to_col_major_f16(loaded[f"{p}.self_attn.v_proj.weight"].data, 16, 16)
                host_weights[wo_w] = _to_col_major_f16(loaded[f"{p}.self_attn.o_proj.weight"].data, 16, 16)

                n1 = f"l{layer}_n1"
                n1_f16 = f"l{layer}_n1_f16"
                q = f"l{layer}_q"
                k = f"l{layer}_k"
                v = f"l{layer}_v"
                attn = f"l{layer}_attn"
                attn_f16 = f"l{layer}_attn_f16"
                h_out = f"l{layer}_h_out"
                for tname, dtype in (
                    (n1, "fp32"),
                    (n1_f16, "fp16"),
                    (q, "fp32"),
                    (k, "fp32"),
                    (v, "fp32"),
                    (attn, "fp32"),
                    (attn_f16, "fp16"),
                    (h_out, "fp32"),
                ):
                    tensors[tname] = TensorSpec(tname, (8, 16), dtype, role="intermediate")

                nodes.extend([
                    OpNode(f"l{layer}_rms1", OpKind.RMSNORM, (cur, rms1_w), (n1,), {"eps": 1e-5}),
                    OpNode(f"l{layer}_cast", OpKind.CAST, (n1,), (n1_f16,), {"target_dtype": "fp16"}),
                    OpNode(f"l{layer}_q_mm", OpKind.MATMUL, (n1_f16, wq_w), (q,)),
                    OpNode(f"l{layer}_k_mm", OpKind.MATMUL, (n1_f16, wk_w), (k,)),
                    OpNode(f"l{layer}_v_mm", OpKind.MATMUL, (n1_f16, wv_w), (v,)),
                    OpNode(f"l{layer}_attn_op", OpKind.ATTENTION, (q, k, v), (attn,)),
                    OpNode(f"l{layer}_attn_cast", OpKind.CAST, (attn,), (attn_f16,), {"target_dtype": "fp16"}),
                    OpNode(f"l{layer}_o_mm", OpKind.MATMUL, (attn_f16, wo_w), (h_out,)),
                ])
                cur = h_out

            nodes.append(OpNode("final_rms", OpKind.RMSNORM, (cur, "final_norm_w"), ("y",), {"eps": 1e-5}))
            graph = CompiledGraph.create(
                name="micro_llama_resident_tcu",
                tensors=tensors,
                inputs=("x",),
                weights=tuple(host_weights.keys()),
                outputs=("y",),
                nodes=nodes,
            )
            fused, report = fuse_graph(graph)
            self.assertEqual(report.rmsnorm_cast_fusions, 2)

            plan = plan_resident_execution(fused, alignment=64)
            self.assertLess(plan.pooled_bytes, plan.naive_bytes)
            self.assertEqual(plan.intermediate_host_copy_bytes, 0)

            x_vals = [0.125 * ((i % 9) - 4) for i in range(8 * 16)]
            with rv2.ResidentContext.open(self.backend) as ctx:
                results, record, allocated = plan.execute(
                    ctx,
                    host_inputs={"x": x_vals},
                    host_weights=host_weights,
                )
                self.assertEqual(record.h2d_bytes_during_run, 0)
                self.assertEqual(record.d2h_bytes_during_run, 0)
                self.assertGreater(record.d2d_bytes_during_run, 0)
                self.assertIn("matmul", record.op_sequence)
                self.assertIn("rmsnorm_fp32", record.op_sequence)
                self.assertIn("attention_fp32", record.op_sequence)

                y_vals = results["y"]
                self.assertEqual(len(y_vals), 8 * 16)
                self.assertTrue(all(math.isfinite(v) for v in y_vals))  # type: ignore[arg-type]

                for buf in reversed(allocated):
                    buf.close()

    def test_mmap_use_after_close_and_empty_tensor_handling(self):
        tensors = {
            "empty_f32": st.TensorData("F32", (0, 4), b""),
            "vec_f16": st.TensorData("F16", (1, 4), st.pack_f16([1.0, -0.5, 0.25, 2.0])),
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "edge.safetensors"
            st.write_safetensors(path, tensors)
            sf = st.open_safetensors(path, use_mmap=True)
            self.assertEqual(sf.info("empty_f32").nbytes, 0)
            mv = sf.tensor_view("vec_f16")
            self.assertEqual(bytes(mv), st.pack_f16([1.0, -0.5, 0.25, 2.0]))
            mv.release()
            sf.close()
            sf.close()  # Idempotent close
            with self.assertRaises(st.SafetensorsError):
                sf.tensor_view("vec_f16")

    def test_onnx_graphproto_duck_type_and_all_operators(self):
        def _dim(v: int) -> types.SimpleNamespace:
            return types.SimpleNamespace(dim_value=v)

        def _vi(name: str, shape: list[int], elem_type: int) -> types.SimpleNamespace:
            return types.SimpleNamespace(
                name=name,
                type=types.SimpleNamespace(
                    tensor_type=types.SimpleNamespace(
                        elem_type=elem_type,
                        shape=types.SimpleNamespace(dim=[_dim(d) for d in shape]),
                    )
                ),
            )

        def _attr_float(name: str, val: float) -> types.SimpleNamespace:
            return types.SimpleNamespace(name=name, type=1, f=val)

        def _attr_int(name: str, val: int) -> types.SimpleNamespace:
            return types.SimpleNamespace(name=name, type=2, i=val)

        proto = types.SimpleNamespace(
            graph=types.SimpleNamespace(
                name="proto_smoke",
                input=[_vi("x", [8, 16], 1)],
                initializer=[
                    types.SimpleNamespace(name="w_rms", dims=[1, 16], data_type=1),
                    types.SimpleNamespace(name="w_attn", dims=[16, 16], data_type=1),
                ],
                output=[_vi("out", [8, 16], 1)],
                value_info=[],
                node=[
                    types.SimpleNamespace(
                        name="rms", op_type="RMSNormalization",
                        input=["x", "w_rms"], output=["n"],
                        attribute=[_attr_float("epsilon", 1e-5)],
                    ),
                    types.SimpleNamespace(
                        name="sm", op_type="Softmax",
                        input=["n"], output=["s"],
                        attribute=[_attr_int("axis", -1)],
                    ),
                    types.SimpleNamespace(
                        name="relu", op_type="Relu",
                        input=["s"], output=["r"],
                        attribute=[],
                    ),
                    types.SimpleNamespace(
                        name="mm", op_type="MatMul",
                        input=["r", "w_attn"], output=["out"],
                        attribute=[],
                    ),
                ],
            )
        )
        ir = lower_onnx_graph(proto)
        validate_graph(ir)
        self.assertEqual([n.op for n in ir.nodes], [OpKind.RMSNORM, OpKind.SOFTMAX, OpKind.RELU, OpKind.MATMUL])

    def test_fx_sdpa_layernorm_linear_bias_and_kv_cache_ops(self):
        fx_spec = {
            "name": "DecoderHeadWithSDPA",
            "modules": {
                "ln": {"type": "nn.LayerNorm", "weight_shape": [16], "bias_shape": [16], "dtype": "fp32", "eps": 1e-5},
                "q_proj": {"type": "nn.Linear", "weight_shape": [16, 16], "bias_shape": [16], "dtype": "fp32"},
                "k_proj": {"type": "nn.Linear", "weight_shape": [16, 16], "dtype": "fp32"},
                "v_proj": {"type": "nn.Linear", "weight_shape": [16, 16], "dtype": "fp32"},
            },
            "nodes": [
                {"op": "placeholder", "name": "x", "target": "x", "args": [], "meta": {"shape": [8, 16], "dtype": "fp32"}},
                {"op": "call_module", "name": "ln_x", "target": "ln", "args": ["x"]},
                {"op": "call_module", "name": "q", "target": "q_proj", "args": ["ln_x"]},
                {"op": "call_module", "name": "k", "target": "k_proj", "args": ["ln_x"]},
                {"op": "call_module", "name": "v", "target": "v_proj", "args": ["ln_x"]},
                {"op": "call_function", "name": "attn", "target": "torch.nn.functional.scaled_dot_product_attention", "args": ["q", "k", "v"], "kwargs": {"is_causal": True}},
                {"op": "call_method", "name": "attn_f16", "target": "to", "args": ["attn"], "kwargs": {"dtype": "torch.float16"}},
                {"op": "output", "name": "output", "target": "output", "args": ["attn_f16"]},
            ],
        }
        ir = lower_fx_trace_spec(fx_spec)
        validate_graph(ir)
        self.assertEqual(
            [n.op for n in ir.nodes],
            [OpKind.LAYERNORM, OpKind.LINEAR, OpKind.LINEAR, OpKind.LINEAR, OpKind.ATTENTION, OpKind.CAST],
        )
        self.assertEqual(ir.tensors["attn_f16"].dtype, "fp16")

        kv_graph = CompiledGraph.create(
            name="gqa_decode_step",
            tensors={
                "q": TensorSpec("q", (1, 16), "fp32", role="input"),
                "k_new": TensorSpec("k_new", (1, 16), "fp32", role="input"),
                "v_new": TensorSpec("v_new", (1, 16), "fp32", role="input"),
                "k_cache_in": TensorSpec("k_cache_in", (7, 16), "fp32", role="input"),
                "v_cache_in": TensorSpec("v_cache_in", (7, 16), "fp32", role="input"),
                "k_cache": TensorSpec("k_cache", (8, 16), "fp32", role="intermediate"),
                "v_cache": TensorSpec("v_cache", (8, 16), "fp32", role="intermediate"),
                "y": TensorSpec("y", (1, 16), "fp32", role="output"),
            },
            inputs=("q", "k_new", "v_new", "k_cache_in", "v_cache_in"),
            outputs=("y",),
            nodes=(
                OpNode("append_k", OpKind.KV_CACHE_APPEND, ("k_cache_in", "k_new"), ("k_cache",)),
                OpNode("append_v", OpKind.KV_CACHE_APPEND, ("v_cache_in", "v_new"), ("v_cache",)),
                OpNode("gqa", OpKind.GQA_DECODE_ATTENTION, ("q", "k_cache", "v_cache"), ("y",)),
            ),
        )
        plan = plan_resident_execution(kv_graph, alignment=64)
        self.assertEqual(plan.intermediate_host_copy_bytes, 0)
        self.assertEqual(len(plan.steps), 3)


if __name__ == "__main__":
    unittest.main()
