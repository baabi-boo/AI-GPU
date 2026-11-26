# SPDX-License-Identifier: Apache-2.0
"""Additive device-resident tensor handles and explicit serial multi-op graphs."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import os
import struct
import sys
import threading
import weakref

from vortex_ai import _api


RESIDENT_V2_API = 1
_IMPORT_PID = os.getpid()
_UINT32_MAX = (1 << 32) - 1
_UINT64_MAX = (1 << 64) - 1

_DTYPE_BYTES = {
    "fp32": 4,
    "fp16": 2,
    "bf16": 2,
}
_VALID_LAYOUTS = ("row_major", "column_major")

_OPS_V2_UNARY = frozenset((
    "relu_fp32",
    "gelu_fp32",
    "softmax_fp32",
    "cast_fp32_to_fp16",
    "cast_fp16_to_fp32",
    "cast_fp32_to_bf16",
    "cast_bf16_to_fp32",
))
_OPS_V2_NORM = frozenset(("rmsnorm_fp32", "layernorm_fp32"))
_OPS_V2_ALL = _OPS_V2_UNARY | _OPS_V2_NORM | frozenset(("attention_fp32",))
_MATMUL_SHAPES = frozenset(((8, 4, 8), (8, 4, 16), (16, 8, 16)))

_CONTEXT_LOCK = threading.Lock()
_ACTIVE_CONTEXT: weakref.ReferenceType[ResidentContext] | None = None
_CONTEXT_POISONED = False


def _process_check():
    _api._process_check(_IMPORT_PID)


def _positive_int(value, name, *, maximum=_UINT32_MAX):
    return _api._integer(value, name, maximum=maximum, minimum=1)


def _nonneg_int(value, name, *, maximum=_UINT64_MAX):
    return _api._integer(value, name, maximum=maximum, minimum=0)


def _validate_dtype(dtype):
    _api._text(dtype, "dtype")
    if dtype not in _DTYPE_BYTES:
        raise ValueError(f"unsupported resident dtype: {dtype!r}")
    return dtype


def _validate_layout(layout):
    _api._text(layout, "layout")
    if layout not in _VALID_LAYOUTS:
        raise ValueError(f"layout must be 'row_major' or 'column_major', got {layout!r}")
    return layout


def _validate_shape(shape):
    if type(shape) is not tuple or len(shape) != 2:
        raise TypeError("shape must be an exact tuple of two positive ints")
    rows = _positive_int(shape[0], "shape[0]")
    cols = _positive_int(shape[1], "shape[1]")
    nbytes_max = min(_UINT64_MAX, sys.maxsize)
    if rows * cols * 4 > nbytes_max:
        raise OverflowError("tensor byte extent exceeds addressable memory")
    return (rows, cols)


def _expected_byte_strides(shape, dtype, layout):
    elem_bytes = _DTYPE_BYTES[dtype]
    rows, cols = shape
    if layout == "row_major":
        return (cols * elem_bytes, elem_bytes)
    return (elem_bytes, rows * elem_bytes)


def _try_import_torch():
    try:
        return importlib.import_module("torch")
    except (ImportError, OSError):
        return None


def torch_available():
    """Return True iff PyTorch is importable in the current environment."""
    return _try_import_torch() is not None


def _reject_autograd_object(value, torch_mod=None):
    # Reject reverse-mode or forward-mode autograd tracking even under no_grad().
    if getattr(value, "requires_grad", False):
        raise ValueError("aigpu_sdk.resident_v2 rejects tensors with requires_grad=True")
    if getattr(value, "grad_fn", None) is not None:
        raise ValueError("aigpu_sdk.resident_v2 rejects tensors attached to an autograd graph")
    if torch_mod is not None:
        with torch_mod.inference_mode(False):
            tangent = torch_mod.autograd.forward_ad.unpack_dual(value).tangent
        if tangent is not None:
            raise ValueError("aigpu_sdk.resident_v2 rejects forward-AD dual tensors")


def pack_f32_sequence(values):
    """Pure-stdlib helper to pack finite/IEEE float values as little-endian FP32 bytes."""
    if isinstance(values, (bytes, bytearray, memoryview)):
        view = memoryview(values)
        try:
            if view.ndim != 1 or view.itemsize != 1 or not view.c_contiguous:
                raise ValueError("byte input must be contiguous 1-D bytes")
            if view.nbytes == 0 or (view.nbytes % 4) != 0:
                raise ValueError("FP32 byte input length must be a positive multiple of 4")
            return bytes(view)
        finally:
            view.release()
    items = list(values)
    if not items:
        raise ValueError("sequence must not be empty")
    for item in items:
        if type(item) not in (int, float):
            raise TypeError("FP32 sequence elements must be int or float, excluding bool")
    return struct.pack(f"<{len(items)}f", *items)


def unpack_f32_sequence(data):
    """Pure-stdlib helper to unpack little-endian FP32 bytes into Python floats."""
    view = memoryview(data)
    try:
        if view.ndim != 1 or view.itemsize != 1 or not view.c_contiguous:
            raise ValueError("data must be contiguous 1-D byte storage")
        if view.nbytes == 0 or (view.nbytes % 4) != 0:
            raise ValueError("data byte length must be a positive multiple of 4")
        return struct.unpack(f"<{view.nbytes // 4}f", view)
    finally:
        view.release()


def _reset_global_state_for_tests():
    # Internal helper used only when unit tests reset mock single-context state.
    global _ACTIVE_CONTEXT, _CONTEXT_POISONED
    with _CONTEXT_LOCK:
        _ACTIVE_CONTEXT = None
        _CONTEXT_POISONED = False


@dataclass(frozen=True, slots=True)
class GraphOp:
    """Validated descriptor for one device-resident operator node."""

    op_name: str
    inputs: tuple[ResidentTensor, ...]
    outputs: tuple[ResidentTensor, ...]
    eps: float = 1e-5
    region: tuple[int, int, int] | None = None
    src_origin: tuple[int, int, int] = (0, 0, 0)
    dst_origin: tuple[int, int, int] = (0, 0, 0)


@dataclass(frozen=True, slots=True)
class GraphExecutionRecord:
    """Execution summary proving zero intermediate host<->device transfers during run()."""

    op_count: int
    op_sequence: tuple[str, ...]
    h2d_bytes_during_run: int
    d2h_bytes_during_run: int
    d2d_bytes_during_run: int
    device_launches: int


class _SessionResidentBridge:
    """Adapter bridging an explicit resident backend or qualified Session metadata."""

    def __init__(self, backend):
        required = ("alloc_buffer", "free_buffer", "write_buffer",
                    "read_buffer", "copy_buffer", "execute_op")
        missing = [name for name in required if not callable(getattr(backend, name, None))]
        if missing:
            raise TypeError(
                "resident backend must implement: " + ", ".join(required)
                + f" (missing: {', '.join(missing)})"
            )
        self._backend = backend

    def alloc_buffer(self, nbytes):
        return self._backend.alloc_buffer(nbytes)

    def free_buffer(self, handle):
        return self._backend.free_buffer(handle)

    def write_buffer(self, handle, data):
        return self._backend.write_buffer(handle, data)

    def read_buffer(self, handle, nbytes):
        return self._backend.read_buffer(handle, nbytes)

    def copy_buffer(self, dst_handle, src_handle, nbytes, *,
                    src_origin=(0, 0, 0), dst_origin=(0, 0, 0),
                    region=None, src_pitch=0, dst_pitch=0):
        return self._backend.copy_buffer(
            dst_handle, src_handle, nbytes,
            src_origin=src_origin, dst_origin=dst_origin,
            region=region, src_pitch=src_pitch, dst_pitch=dst_pitch,
        )

    def execute_op(self, op_spec):
        return self._backend.execute_op(op_spec)

    def memory_info(self):
        fn = getattr(self._backend, "memory_info", None)
        if callable(fn):
            return fn()
        return (0, 0, 0)

    def close(self):
        fn = getattr(self._backend, "close", None)
        if callable(fn):
            return fn()
        return None


class ResidentTensor:
    """Device-resident buffer handle bound to one open ResidentContext."""

    __slots__ = (
        "_context_ref",
        "_handle",
        "_device_addr",
        "_shape",
        "_dtype",
        "_layout",
        "_strides",
        "_nbytes",
        "_closed",
        "_initialized",
        "__weakref__",
    )

    def __init__(self):
        raise TypeError("Use ResidentContext.allocate(), from_bytes(), or from_torch()")

    @classmethod
    def _create(cls, context, *, handle, device_addr, shape, dtype, layout, initialized):
        obj = object.__new__(cls)
        obj._context_ref = weakref.ref(context)
        obj._handle = handle
        obj._device_addr = device_addr
        obj._shape = shape
        obj._dtype = dtype
        obj._layout = layout
        obj._strides = _expected_byte_strides(shape, dtype, layout)
        obj._nbytes = shape[0] * shape[1] * _DTYPE_BYTES[dtype]
        obj._closed = False
        obj._initialized = initialized
        return obj

    def _require_live(self):
        _process_check()
        if self._closed:
            raise _api.BindingError("ResidentTensor is closed; use-after-close is forbidden",
                                    kind="state")
        ctx = self._context_ref()
        if ctx is None or ctx._closed or ctx._closing:
            raise _api.BindingError("Owning ResidentContext is closed", kind="state")
        return ctx

    @property
    def shape(self):
        return self._shape

    @property
    def dtype(self):
        return self._dtype

    @property
    def layout(self):
        return self._layout

    @property
    def strides(self):
        return self._strides

    @property
    def nbytes(self):
        return self._nbytes

    @property
    def closed(self):
        return self._closed

    @property
    def device_addr(self):
        self._require_live()
        return self._device_addr

    def write(self, data):
        """Explicitly transfer host bytes into this device-resident buffer (H2D)."""
        ctx = self._require_live()
        view = _api._byte_view(data, self._nbytes)
        try:
            payload = bytes(view)
        finally:
            view.release()
        with ctx._gate:
            ctx._ensure_open()
            ctx._bridge.write_buffer(self._handle, payload)
            ctx._h2d_bytes += self._nbytes
            self._initialized = True

    def write_f32(self, values):
        """Pack an explicit Python float sequence and upload it (FP32 H2D)."""
        if self._dtype != "fp32":
            raise ValueError("write_f32 requires a ResidentTensor with dtype='fp32'")
        raw = pack_f32_sequence(values)
        if len(raw) != self._nbytes:
            raise ValueError(f"expected {self._nbytes // 4} float32 values, got {len(raw) // 4}")
        self.write(raw)

    def to_bytes(self):
        """Explicitly read device-resident bytes back to host memory (D2H)."""
        ctx = self._require_live()
        with ctx._gate:
            ctx._ensure_open()
            data = ctx._bridge.read_buffer(self._handle, self._nbytes)
            if type(data) is not bytes or len(data) != self._nbytes:
                raise _api.BindingError("Resident backend returned invalid read payload",
                                        kind="protocol")
            ctx._d2h_bytes += self._nbytes
            return data

    def to_floats(self):
        """Read back FP32 device-resident storage as a tuple of Python floats."""
        if self._dtype != "fp32":
            raise ValueError("to_floats requires a ResidentTensor with dtype='fp32'")
        return unpack_f32_sequence(self.to_bytes())

    def to_torch(self, torch_mod=None):
        """Materialize an independent CPU torch.Tensor copy (explicit D2H)."""
        torch_mod = torch_mod if torch_mod is not None else _try_import_torch()
        if torch_mod is None:
            raise ImportError(
                "PyTorch is not installed; use to_bytes() or to_floats() for stdlib fallback"
            )
        if self._layout != "row_major":
            raise ValueError("to_torch currently supports row_major resident tensors")
        dtype_map = {
            "fp32": torch_mod.float32,
            "fp16": torch_mod.float16,
            "bf16": torch_mod.bfloat16,
        }
        raw = self.to_bytes()
        return (
            torch_mod.frombuffer(bytearray(raw), dtype=dtype_map[self._dtype])
            .clone()
            .view(*self._shape)
        )

    @classmethod
    def from_torch(cls, context, tensor, *, layout="row_major", torch_mod=None):
        """Explicitly validate and upload a CPU torch.Tensor (no autograd)."""
        if type(context) is not ResidentContext:
            raise TypeError("context must be an exact ResidentContext")
        _reject_autograd_object(tensor, torch_mod=None)
        torch_mod = torch_mod if torch_mod is not None else _try_import_torch()
        if torch_mod is None:
            raise ImportError(
                "PyTorch is not installed; use ResidentContext.from_bytes() for stdlib fallback"
            )
        _reject_autograd_object(tensor, torch_mod=torch_mod)
        if type(tensor) is not torch_mod.Tensor:
            raise TypeError("tensor must be an exact torch.Tensor; subclasses are unsupported")
        if tensor.layout != torch_mod.strided or tensor.device.type != "cpu":
            raise ValueError("tensor must use ordinary strided CPU storage")
        if tensor.is_neg() or tensor.is_conj():
            raise ValueError("unresolved negative or conjugate views are unsupported")
        if tensor.ndim != 2 or any(type(dim) is not int for dim in tensor.shape):
            raise ValueError("tensor must have two concrete dimensions")
        if tensor.storage_offset() != 0:
            raise ValueError("tensor must have storage offset zero")
        if tensor.untyped_storage().nbytes() != tensor.numel() * tensor.element_size():
            raise ValueError("tensor must occupy exactly its packed storage extent")

        dtype_map = {
            torch_mod.float32: "fp32",
            torch_mod.float16: "fp16",
            torch_mod.bfloat16: "bf16",
        }
        if tensor.dtype not in dtype_map:
            raise ValueError("tensor dtype must be float32, float16, or bfloat16")
        dtype = dtype_map[tensor.dtype]
        shape = tuple(tensor.shape)
        _validate_layout(layout)
        expected_elem_strides = (shape[1], 1) if layout == "row_major" else (1, shape[0])
        if tuple(tensor.stride()) != expected_elem_strides:
            raise ValueError(f"tensor strides {tuple(tensor.stride())} do not match {layout} {expected_elem_strides}")

        physical = tensor.t() if layout == "column_major" else tensor
        if dtype == "fp32":
            vals = physical.view(torch_mod.int32).flatten().tolist()
            raw = struct.pack(f"<{len(vals)}i", *vals)
        else:
            vals = physical.view(torch_mod.int16).flatten().tolist()
            raw = struct.pack(f"<{len(vals)}h", *vals)
        return context.from_bytes(raw, shape=shape, dtype=dtype, layout=layout)

    def close(self):
        """Explicitly free the device-resident buffer and unregister from its context."""
        _process_check()
        if self._closed:
            return
        ctx = self._context_ref()
        if ctx is None:
            self._closed = True
            return
        with ctx._gate:
            if self._closed:
                return
            try:
                ctx._bridge.free_buffer(self._handle)
                ctx._free_count += 1
            except BaseException as exc:
                ctx._mark_poisoned()
                raise _api.BindingError("Failed to free resident device buffer",
                                        kind="cleanup", close_error=exc) from exc
            finally:
                self._closed = True
                self._handle = None
                self._device_addr = 0
                ctx._tensors.pop(id(self), None)

    def __enter__(self):
        self._require_live()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class ResidentGraph:
    """Explicit serial multi-op graph over device-resident tensors."""

    __slots__ = ("_context_ref", "_ops", "_closed", "_last_record", "__weakref__")

    def __init__(self, context):
        _process_check()
        if type(context) is not ResidentContext:
            raise TypeError("ResidentGraph requires an exact ResidentContext")
        context._ensure_open()
        self._context_ref = weakref.ref(context)
        self._ops = []
        self._closed = False
        self._last_record = None

    def _require_open(self):
        _process_check()
        if self._closed:
            raise _api.BindingError("ResidentGraph is closed", kind="state")
        ctx = self._context_ref()
        if ctx is None or ctx._closed or ctx._closing:
            raise _api.BindingError("Owning ResidentContext is closed", kind="state")
        return ctx

    def _validate_tensor(self, ctx, tensor, role):
        _reject_autograd_object(tensor)
        if type(tensor) is not ResidentTensor:
            raise TypeError(f"{role} must be a ResidentTensor; implicit host conversion is forbidden")
        owner = tensor._require_live()
        if owner is not ctx:
            raise _api.BindingError(f"{role} belongs to a different ResidentContext", kind="state")
        return tensor

    def _check_disjoint(self, tensors):
        seen_ids = set()
        for t in tensors:
            if id(t) in seen_ids:
                raise ValueError("operator operands and output must be pairwise disjoint buffers")
            seen_ids.add(id(t))

    def add_op(self, op_name, inputs, outputs, *, eps=1e-5,
               region=None, src_origin=(0, 0, 0), dst_origin=(0, 0, 0)):
        """Append one validated device-resident operation node."""
        ctx = self._require_open()
        _api._text(op_name, "op_name")
        if type(inputs) is not tuple:
            inputs = tuple(inputs)
        if type(outputs) is not tuple:
            outputs = tuple(outputs)
        if not inputs or not outputs:
            raise ValueError("inputs and outputs must be nonempty")

        checked_in = tuple(self._validate_tensor(ctx, t, f"input[{i}]")
                           for i, t in enumerate(inputs))
        checked_out = tuple(self._validate_tensor(ctx, t, f"output[{i}]")
                            for i, t in enumerate(outputs))
        self._check_disjoint(checked_in + checked_out)

        if op_name in _OPS_V2_UNARY:
            if len(checked_in) != 1 or len(checked_out) != 1:
                raise ValueError(f"{op_name} requires exactly 1 input and 1 output")
            a, d = checked_in[0], checked_out[0]
            if a.shape != d.shape or a.layout != "row_major" or d.layout != "row_major":
                raise ValueError(f"{op_name} requires matching row_major shapes")
            expected_in, expected_out = {
                "relu_fp32": ("fp32", "fp32"),
                "gelu_fp32": ("fp32", "fp32"),
                "softmax_fp32": ("fp32", "fp32"),
                "cast_fp32_to_fp16": ("fp32", "fp16"),
                "cast_fp16_to_fp32": ("fp16", "fp32"),
                "cast_fp32_to_bf16": ("fp32", "bf16"),
                "cast_bf16_to_fp32": ("bf16", "fp32"),
            }[op_name]
            if a.dtype != expected_in or d.dtype != expected_out:
                raise ValueError(f"{op_name} dtype mismatch: got ({a.dtype} -> {d.dtype})")
        elif op_name == "rmsnorm_fp32":
            if len(checked_in) != 2 or len(checked_out) != 1:
                raise ValueError("rmsnorm_fp32 requires (x, weight) -> dst")
            x, w, d = checked_in[0], checked_in[1], checked_out[0]
            if (x.dtype != "fp32" or w.dtype != "fp32" or d.dtype != "fp32"
                    or x.layout != "row_major" or d.layout != "row_major"):
                raise ValueError("rmsnorm_fp32 requires row_major fp32 tensors")
            if x.shape != d.shape or w.shape != (1, x.shape[1]):
                raise ValueError("rmsnorm_fp32 weight must have shape (1, cols)")
        elif op_name == "layernorm_fp32":
            if len(checked_in) != 3 or len(checked_out) != 1:
                raise ValueError("layernorm_fp32 requires (x, gamma, beta) -> dst")
            x, g, b, d = checked_in[0], checked_in[1], checked_in[2], checked_out[0]
            if any(t.dtype != "fp32" or t.layout != "row_major" for t in (x, g, b, d)):
                raise ValueError("layernorm_fp32 requires row_major fp32 tensors")
            if x.shape != d.shape or g.shape != (1, x.shape[1]) or b.shape != (1, x.shape[1]):
                raise ValueError("layernorm_fp32 gamma/beta must have shape (1, cols)")
        elif op_name == "attention_fp32":
            if len(checked_in) != 3 or len(checked_out) != 1:
                raise ValueError("attention_fp32 requires (Q, K, V) -> dst")
            q, k, v, d = checked_in[0], checked_in[1], checked_in[2], checked_out[0]
            if any(t.dtype != "fp32" or t.layout != "row_major" for t in (q, k, v, d)):
                raise ValueError("attention_fp32 requires row_major fp32 tensors")
            if not (q.shape == k.shape == v.shape == d.shape):
                raise ValueError("attention_fp32 requires identical Q, K, V, dst shapes")
            if q.shape[0] > 64 or q.shape[1] > 64:
                raise ValueError("attention_fp32 exceeds seq_len <= 64, d_k <= 64")
        elif op_name == "matmul":
            if len(checked_in) != 2 or len(checked_out) != 1:
                raise ValueError("matmul requires (A, B) -> D")
            a, b, d = checked_in[0], checked_in[1], checked_out[0]
            if a.dtype not in ("fp16", "bf16") or a.dtype != b.dtype or d.dtype != "fp32":
                raise ValueError("matmul requires matching fp16/bf16 inputs and fp32 output")
            if a.layout != "row_major" or b.layout != "column_major" or d.layout != "row_major":
                raise ValueError("matmul requires row_major A, column_major B, row_major D")
            m, k = a.shape
            kb, n = b.shape
            if k != kb or d.shape != (m, n) or (m, n, k) not in _MATMUL_SHAPES:
                raise ValueError(f"unsupported matmul signature {(m, n, k)}")
        elif op_name == "copy_rect":
            if len(checked_in) != 1 or len(checked_out) != 1:
                raise ValueError("copy_rect requires (src,) -> (dst,)")
            if region is None or len(region) != 3 or any(v <= 0 for v in region):
                raise ValueError("copy_rect requires positive 3-tuple region=(width_bytes, rows, slices)")
        else:
            raise ValueError(f"unsupported resident op: {op_name!r}")

        node = GraphOp(
            op_name=op_name,
            inputs=checked_in,
            outputs=checked_out,
            eps=float(eps),
            region=region,
            src_origin=src_origin,
            dst_origin=dst_origin,
        )
        self._ops.append(node)
        return self

    @property
    def ops(self):
        return tuple(self._ops)

    @property
    def last_record(self):
        return self._last_record

    def run(self):
        """Execute all queued ops serially on-device with zero intermediate H2D/D2H."""
        ctx = self._require_open()
        if not self._ops:
            raise ValueError("ResidentGraph has no operations to execute")
        with ctx._gate:
            ctx._ensure_open()
            for node in self._ops:
                for tensor in node.inputs + node.outputs:
                    owner = tensor._require_live()
                    if owner is not ctx:
                        raise _api.BindingError("Tensor ownership mismatch during run()", kind="state")

            h2d_before = ctx._h2d_bytes
            d2h_before = ctx._d2h_bytes
            d2d_before = ctx._d2d_bytes
            launches = 0
            sequence = []

            for node in self._ops:
                if node.op_name == "copy_rect":
                    src = node.inputs[0]
                    dst = node.outputs[0]
                    ctx._bridge.copy_buffer(
                        dst._handle,
                        src._handle,
                        node.region[0] * node.region[1] * node.region[2],
                        src_origin=node.src_origin,
                        dst_origin=node.dst_origin,
                        region=node.region,
                        src_pitch=src.strides[0],
                        dst_pitch=dst.strides[0],
                    )
                    ctx._d2d_bytes += node.region[0] * node.region[1] * node.region[2]
                else:
                    ctx._bridge.execute_op({
                        "op_name": node.op_name,
                        "inputs": tuple(t._handle for t in node.inputs),
                        "input_addrs": tuple(t._device_addr for t in node.inputs),
                        "input_shapes": tuple(t.shape for t in node.inputs),
                        "input_dtypes": tuple(t.dtype for t in node.inputs),
                        "outputs": tuple(t._handle for t in node.outputs),
                        "output_addrs": tuple(t._device_addr for t in node.outputs),
                        "output_shapes": tuple(t.shape for t in node.outputs),
                        "output_dtypes": tuple(t.dtype for t in node.outputs),
                        "eps": node.eps,
                    })
                    ctx._op_launches += 1
                    launches += 1
                sequence.append(node.op_name)

            record = GraphExecutionRecord(
                op_count=len(self._ops),
                op_sequence=tuple(sequence),
                h2d_bytes_during_run=ctx._h2d_bytes - h2d_before,
                d2h_bytes_during_run=ctx._d2h_bytes - d2h_before,
                d2d_bytes_during_run=ctx._d2d_bytes - d2d_before,
                device_launches=launches,
            )
            self._last_record = record
            return record

    def close(self):
        _process_check()
        self._closed = True
        self._ops.clear()


class ResidentContext:
    """Single-context serial owner for device-resident tensors and graphs."""

    __slots__ = (
        "_bridge",
        "_gate",
        "_tensors",
        "_closed",
        "_closing",
        "_h2d_bytes",
        "_d2h_bytes",
        "_d2d_bytes",
        "_alloc_count",
        "_free_count",
        "_op_launches",
        "__weakref__",
    )

    def __init__(self):
        raise TypeError("Use ResidentContext.open(backend) to create the single active context")

    @classmethod
    def open(cls, backend):
        """Open the sole process-local resident context (no multi-context concurrency)."""
        _process_check()
        if cls is not ResidentContext:
            raise TypeError("ResidentContext subclasses are unsupported")
        global _ACTIVE_CONTEXT
        bridge = _SessionResidentBridge(backend)
        with _CONTEXT_LOCK:
            if _CONTEXT_POISONED:
                raise _api.BindingError(
                    "Process resident context is poisoned after cleanup failure; restart process",
                    kind="state",
                )
            existing = _ACTIVE_CONTEXT() if _ACTIVE_CONTEXT is not None else None
            if existing is not None and not existing._closed:
                raise _api.BindingError(
                    "SimX/native serial ownership permits only one live ResidentContext per process",
                    kind="state",
                )
            ctx = object.__new__(cls)
            ctx._bridge = bridge
            ctx._gate = _api._Gate()
            ctx._tensors = {}
            ctx._closed = False
            ctx._closing = False
            ctx._h2d_bytes = 0
            ctx._d2h_bytes = 0
            ctx._d2d_bytes = 0
            ctx._alloc_count = 0
            ctx._free_count = 0
            ctx._op_launches = 0
            _ACTIVE_CONTEXT = weakref.ref(ctx)
            return ctx

    def _ensure_open(self):
        if self._closed or self._closing:
            raise _api.BindingError("ResidentContext is closed", kind="state")

    def _mark_poisoned(self):
        global _CONTEXT_POISONED
        with _CONTEXT_LOCK:
            _CONTEXT_POISONED = True

    @property
    def closed(self):
        return self._closed

    @property
    def stats(self):
        return {
            "live_tensors": len(self._tensors),
            "alloc_count": self._alloc_count,
            "free_count": self._free_count,
            "h2d_bytes": self._h2d_bytes,
            "d2h_bytes": self._d2h_bytes,
            "d2d_bytes": self._d2d_bytes,
            "op_launches": self._op_launches,
        }

    def allocate(self, shape, *, dtype="fp32", layout="row_major"):
        """Allocate an uninitialized device-resident tensor buffer."""
        _process_check()
        shape = _validate_shape(shape)
        dtype = _validate_dtype(dtype)
        layout = _validate_layout(layout)
        nbytes = shape[0] * shape[1] * _DTYPE_BYTES[dtype]
        with self._gate:
            self._ensure_open()
            alloc = self._bridge.alloc_buffer(nbytes)
            if type(alloc) is not tuple or len(alloc) != 2:
                raise _api.BindingError("Resident backend alloc_buffer must return (handle, dev_addr)",
                                        kind="protocol")
            handle, dev_addr = alloc
            _nonneg_int(dev_addr, "device_addr")
            if dev_addr == 0 or (dev_addr % 4) != 0:
                self._bridge.free_buffer(handle)
                raise _api.BindingError("Resident backend returned unaligned or null device address",
                                        kind="protocol")
            tensor = ResidentTensor._create(
                self,
                handle=handle,
                device_addr=dev_addr,
                shape=shape,
                dtype=dtype,
                layout=layout,
                initialized=False,
            )
            self._tensors[id(tensor)] = tensor
            self._alloc_count += 1
            return tensor

    def from_bytes(self, data, *, shape, dtype="fp32", layout="row_major"):
        """Allocate a device-resident tensor and explicitly upload host bytes (H2D)."""
        tensor = self.allocate(shape, dtype=dtype, layout=layout)
        try:
            tensor.write(data)
            return tensor
        except BaseException:
            tensor.close()
            raise

    def from_f32(self, values, *, shape, layout="row_major"):
        """Allocate an FP32 resident tensor from a pure-stdlib Python float sequence."""
        raw = pack_f32_sequence(values)
        return self.from_bytes(raw, shape=shape, dtype="fp32", layout=layout)

    def from_torch(self, tensor, *, layout="row_major", torch_mod=None):
        """Explicitly validate and upload a CPU torch.Tensor without autograd."""
        return ResidentTensor.from_torch(self, tensor, layout=layout, torch_mod=torch_mod)

    def graph(self):
        """Create a serial ResidentGraph bound to this ResidentContext."""
        return ResidentGraph(self)

    def live_tensors(self):
        with self._gate:
            return tuple(self._tensors.values())

    def close(self, *, release_tensors=False):
        """Close the context; rejects live tensors unless release_tensors=True."""
        _process_check()
        global _ACTIVE_CONTEXT
        with self._gate:
            if self._closed:
                return
            if self._tensors and not release_tensors:
                raise _api.BindingError(
                    f"Cannot close ResidentContext with {len(self._tensors)} open ResidentTensor(s)",
                    kind="state",
                )
            self._closing = True
            first_error = None
            for tensor in tuple(self._tensors.values()):
                try:
                    self._bridge.free_buffer(tensor._handle)
                    self._free_count += 1
                except BaseException as exc:
                    if first_error is None:
                        first_error = exc
                finally:
                    tensor._closed = True
                    tensor._handle = None
                    tensor._device_addr = 0
                    self._tensors.pop(id(tensor), None)
            try:
                self._bridge.close()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
            self._closed = True
            if first_error is not None:
                self._mark_poisoned()
                raise _api.BindingError("ResidentContext cleanup failed; process poisoned",
                                        kind="cleanup", close_error=first_error) from first_error
            with _CONTEXT_LOCK:
                if _ACTIVE_CONTEXT is not None and _ACTIVE_CONTEXT() is self:
                    _ACTIVE_CONTEXT = None

    def __enter__(self):
        _process_check()
        with self._gate:
            self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc is not None:
            try:
                self.close(release_tensors=True)
            except BaseException:
                pass
            return False
        self.close()
        return False


__all__ = (
    "RESIDENT_V2_API",
    "GraphExecutionRecord",
    "GraphOp",
    "ResidentContext",
    "ResidentGraph",
    "ResidentTensor",
    "pack_f32_sequence",
    "torch_available",
    "unpack_f32_sequence",
)
