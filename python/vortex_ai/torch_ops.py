# SPDX-License-Identifier: Apache-2.0
"""Versioned eager PyTorch operators over explicitly owned native sessions."""

from __future__ import annotations

import itertools
import os
import platform
import struct
import sys
import sysconfig
import time

from . import _api


TORCH_OPS_API = 1
SUPPORTED_TORCH_VERSION = "2.15.0+cpu"
_DEFAULT_POISON = 0x7FC0DEAD
_UINT32_MAX = (1 << 32) - 1
_TOKEN_MAX = (1 << 63) - 1
_WAIT_NS = 100_000_000
_TIMEOUT = 7
_SHAPES = ((8, 4, 8), (8, 4, 16), (16, 8, 16))
_IMPORT_PID = os.getpid()

try:
    import torch
except (ImportError, OSError) as error:
    raise ImportError(
        "The optional Vortex framework adapter requires PyTorch 2.15.0+cpu; "
        "install the pinned CPU framework dependencies before importing "
        "vortex_ai.torch_ops. Base import vortex_ai does not require PyTorch"
    ) from error

if (str(torch.__version__) != SUPPORTED_TORCH_VERSION
        or torch.version.cuda is not None or torch.version.hip is not None):
    raise ImportError("vortex_ai.torch_ops requires exactly PyTorch 2.15.0+cpu")
if (sys.platform != "linux" or platform.machine() != "x86_64"
        or platform.python_implementation() != "CPython"
        or sys.version_info[:2] != (3, 12) or sys.byteorder != "little"
        or sysconfig.get_config_var("Py_GIL_DISABLED")):
    raise ImportError(
        "vortex_ai.torch_ops requires little-endian Linux x86_64 CPython 3.12 with the GIL"
    )

_REGISTRY = {}
_REGISTRY_GATE = _api._Gate()
_TOKENS = itertools.count(1 << 32)


def _process_check():
    _api._process_check(_IMPORT_PID)


def _integer(value, name, maximum):
    if type(value) is not int:
        raise TypeError(f"{name} must be an exact int, excluding bool")
    if value < 0 or value > maximum:
        raise ValueError(f"{name} must be in 0..{maximum}")
    return value


def _mode_check():
    if (torch.is_autocast_enabled("cpu") or torch.compiler.is_compiling()
            or torch.jit.is_tracing()):
        raise RuntimeError("Vortex custom operators support eager inference without autocast or tracing")


def _reject_transform(*_args, **_kwargs):
    raise RuntimeError("Vortex custom operators do not support this PyTorch transform or tensor view")


def _operand(value, name):
    if type(value) is not torch.Tensor:
        raise TypeError(f"{name} must be an exact torch.Tensor; tensor subclasses are unsupported")
    if value.layout != torch.strided or value.device.type != "cpu":
        raise ValueError(f"{name} must use ordinary strided CPU storage")
    if value.dtype not in (torch.float16, torch.bfloat16):
        raise ValueError(f"{name} must have dtype torch.float16 or torch.bfloat16")
    with torch.inference_mode(False):
        tangent = torch.autograd.forward_ad.unpack_dual(value).tangent
    if value.requires_grad or tangent is not None:
        raise ValueError("Vortex custom operators do not support reverse or forward differentiation")
    if value.is_neg() or value.is_conj():
        raise ValueError(f"{name} has an unsupported unresolved negative or conjugate view")
    if value.ndim != 2 or any(type(size) is not int for size in value.shape):
        raise ValueError(f"{name} must have two concrete dimensions")
    if value.storage_offset() != 0:
        raise ValueError(f"{name} must have storage offset zero")
    if value.untyped_storage().nbytes() != value.numel() * value.element_size():
        raise ValueError(f"{name} must occupy exactly its packed storage extent")


def _inputs(a, b, session):
    _operand(a, "A")
    _operand(b, "B")
    m, k = tuple(a.shape)
    kb, n = tuple(b.shape)
    if k != kb or (m, n, k) not in _SHAPES:
        raise ValueError("unsupported (M, N, K) signature for Vortex matmul")
    if tuple(a.stride()) != (k, 1) or tuple(b.stride()) != (1, k):
        raise ValueError("A must have element strides (K,1) and B must have element strides (1,K)")
    dtype = "fp16" if a.dtype == torch.float16 else "bf16"
    if a.dtype != b.dtype or dtype != session.info["format"]:
        raise ValueError("both tensor dtypes must match the qualified native session format")
    return m, n, k, dtype


def _pack(value, *, column_major=False):
    physical = value.t() if column_major else value
    values = physical.view(torch.int16).flatten().tolist()
    return struct.pack(f"<{len(values)}h", *values)


def _output(data, rows, columns):
    if type(data) is not bytes or len(data) != rows * columns * 4:
        raise _api.BindingError("Native output has an invalid FP32 byte extent", kind="protocol")
    return torch.frombuffer(bytearray(data), dtype=torch.float32).clone().view(rows, columns)


def _retain_error(error, adapter):
    operation = None
    try:
        operation = getattr(error, "operation", None)
        pending = adapter._session.pending_operations()
        if operation is None and len(pending) == 1:
            operation = pending[0]
        if operation is None:
            operation = adapter._last_operation
        if operation is not None:
            adapter._last_operation = operation
    except BaseException:
        pass
    _api._attach(error, operation=operation, session=adapter._session)
    try:
        error.adapter = adapter
    except BaseException:
        pass


def _retry_status(status, operation):
    if status.complete:
        status.raise_for_status(operation)
        return False
    if status.validation != "success" or status.primary not in (0, _TIMEOUT) or status.cleanup != 0:
        status.raise_for_status(operation)
    return True


def _wait_budget(adapter, operation, deadline, status=None):
    remaining = deadline - time.monotonic_ns()
    if remaining <= 0:
        raise _api.BindingError(
            "The framework retry deadline expired; ownership is retained. "
            "Inspect pending_operations() and retry bounded native wait or close; timeout is not cancellation",
            status=status, operation=operation, session=adapter._session, kind="timeout")
    return min(_WAIT_NS, remaining)


def _wait_matmul(operation, adapter, deadline):
    status = operation.status
    while _retry_status(status, operation):
        status = operation.wait(_wait_budget(adapter, operation, deadline, status))


def _advance_model(operation, adapter, deadline):
    status = operation.status
    while not status.terminal:
        if (status.status != "in_progress" or status.execution.validation != "success"
                or status.execution.primary not in (0, _TIMEOUT) or status.execution.cleanup != 0):
            status.raise_for_status(operation)
        status = operation.advance(_wait_budget(adapter, operation, deadline, status.execution))
    status.raise_for_status(operation)


def _close_operation(operation, adapter, deadline):
    while True:
        status = operation.close(_wait_budget(adapter, operation, deadline))
        if not _retry_status(status, operation):
            return


def _lookup(token):
    _process_check()
    _integer(token, "session_token", _TOKEN_MAX)
    with _REGISTRY_GATE:
        adapter = _REGISTRY.get(token)
    if adapter is None:
        raise _api.BindingError("Unknown or detached PyTorch session token", kind="state")
    return adapter


class TorchSession:
    """Borrow a native Session until explicit detach; failures retain native owners."""

    __slots__ = ("_session", "_timeout_ns", "_token", "_gate", "_closed", "_last_operation")

    def __init__(self, session, *, timeout_seconds=30.0):
        _process_check()
        if type(self) is not TorchSession or type(session) is not _api.Session:
            raise TypeError("TorchSession requires an exact vortex_ai.Session; subclasses are unsupported")
        if type(timeout_seconds) not in (int, float):
            raise TypeError("timeout_seconds must be an int or float, excluding bool")
        if not 0 < timeout_seconds <= 300 or int(timeout_seconds * 1_000_000_000) == 0:
            raise ValueError("timeout_seconds must be finite and between one nanosecond and 300 seconds")
        self._session = session
        self._timeout_ns = int(timeout_seconds * 1_000_000_000)
        self._gate = _api._Gate()
        self._closed = False
        self._last_operation = None
        self._token = 0
        retained_adapter = self
        try:
            with _REGISTRY_GATE:
                for existing in _REGISTRY.values():
                    if existing._session is session:
                        # A prior constructor may have registered successfully
                        # before interruption prevented assignment by its caller.
                        retained_adapter = existing
                        raise _api.BindingError("This native session already has a PyTorch adapter",
                                                session=session, kind="state")
                self._ready()
                token = next(_TOKENS)
                if token > _TOKEN_MAX:
                    raise OverflowError("PyTorch session token space is exhausted")
                self._token = token
                _REGISTRY[token] = self
        except BaseException as error:
            _retain_error(error, retained_adapter)
            raise

    def _ready(self):
        if self._closed:
            raise _api.BindingError("The PyTorch adapter is detached", session=self._session, kind="state")
        with self._session._gate:
            self._session._ensure_open()
            if not self._session.info:
                raise _api.BindingError(
                    "Native session initialization did not finish; close the retained "
                    "session before opening a new qualified session",
                    session=self._session, kind="state")
        if self._session.pending_operations():
            raise _api.BindingError("Native work is still owned; complete explicit close before a new call",
                                    session=self._session, kind="state")

    @property
    def token(self):
        return self._token

    @property
    def session(self):
        return self._session

    @property
    def last_operation(self):
        return self._last_operation

    def pending_operations(self):
        _process_check()
        return self._session.pending_operations()

    def matmul(self, a, b, *, poison=_DEFAULT_POISON):
        _process_check()
        _integer(poison, "poison", _UINT32_MAX)
        return torch.ops.vortex_ai.matmul_v1(a, b, self._token, poison)

    def fixed_mlp(self, case_id, *, poison=_DEFAULT_POISON):
        _process_check()
        if type(case_id) is not str:
            raise TypeError("case_id must be an exact str")
        _integer(poison, "poison", _UINT32_MAX)
        return torch.ops.vortex_ai.fixed_mlp_v1(case_id, self._token, poison)

    def close(self):
        """Detach after all native owners close; the borrowed session stays open."""
        _process_check()
        with self._gate:
            if not self._closed and self._session.pending_operations():
                raise _api.BindingError("Cannot detach while native work remains owned",
                                        session=self._session, kind="state")
            with _REGISTRY_GATE:
                current = _REGISTRY.get(self._token)
                if current is not None and current is not self:
                    raise _api.BindingError("PyTorch session registry identity differs", kind="protocol")
                self._closed = True
                if current is self:
                    del _REGISTRY[self._token]


def _matmul_eager(a, b, session_token, poison):
    _process_check()
    _mode_check()
    _integer(poison, "poison", _UINT32_MAX)
    adapter = _lookup(session_token)
    with adapter._gate:
        try:
            adapter._ready()
            adapter._last_operation = None
            m, n, k, dtype = _inputs(a, b, adapter._session)
            deadline = time.monotonic_ns() + adapter._timeout_ns
            native_a = _api.Tensor(_pack(a), dtype=dtype, shape=(m, k), layout="row_major")
            native_b = _api.Tensor(_pack(b, column_major=True), dtype=dtype,
                                   shape=(k, n), layout="column_major")
            _wait_budget(adapter, None, deadline)
            operation = adapter._session.submit(native_a, native_b, poison=poison)
            adapter._last_operation = operation
            _wait_matmul(operation, adapter, deadline)
            _close_operation(operation, adapter, deadline)
            return _output(operation.output_bytes(), m, n)
        except BaseException as error:
            _retain_error(error, adapter)
            raise


def _fixed_mlp_eager(case_id, session_token, poison):
    _process_check()
    _mode_check()
    if type(case_id) is not str:
        raise TypeError("case_id must be an exact str")
    _integer(poison, "poison", _UINT32_MAX)
    adapter = _lookup(session_token)
    with adapter._gate:
        try:
            adapter._ready()
            adapter._last_operation = None
            deadline = time.monotonic_ns() + adapter._timeout_ns
            _wait_budget(adapter, None, deadline)
            operation = adapter._session.model(case_id, poison=poison)
            adapter._last_operation = operation
            _advance_model(operation, adapter, deadline)
            _close_operation(operation, adapter, deadline)
            operation.status.raise_for_status(operation)
            return _output(operation.output_bytes(), 16, 4)
        except BaseException as error:
            _retain_error(error, adapter)
            raise


_LIBRARY = torch.library.Library("vortex_ai", "DEF")
_LIBRARY.define("matmul_v1(Tensor a, Tensor b, int session_token, int poison) -> Tensor")
_LIBRARY.define("fixed_mlp_v1(str case_id, int session_token, int poison) -> Tensor")
_LIBRARY.impl("matmul_v1", _matmul_eager, "CPU")
_LIBRARY.impl("matmul_v1", _matmul_eager, "Autograd")
_LIBRARY.impl("fixed_mlp_v1", _fixed_mlp_eager, "CompositeExplicitAutograd")

for _name in ("matmul_v1", "fixed_mlp_v1"):
    for _key in (
        "Meta", "FuncTorchBatched", "FuncTorchVmapMode", "Functionalize",
        "Tracer", "AutocastCPU", "Negative", "Conjugate",
        "FuncTorchDynamicLayerFrontMode",
    ):
        _LIBRARY.impl(_name, _reject_transform, _key)


__all__ = ("TORCH_OPS_API", "SUPPORTED_TORCH_VERSION", "TorchSession")
