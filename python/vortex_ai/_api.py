# SPDX-License-Identifier: Apache-2.0
"""Copying access to a qualified native runtime; no implicit tensor conversion."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import json
import os
import struct
import sys
import threading
from types import MappingProxyType
import weakref


BINDING_API = 1
_IMPORT_PID = os.getpid()
_DEFAULT_TIMEOUT_NS = 100_000_000
_MAX_TIMEOUT_NS = 1_000_000_000
_DEFAULT_POISON = 0x7FC0DEAD
_UINT32_MAX = (1 << 32) - 1
_UINT64_MAX = (1 << 64) - 1
_TIMEOUT = 7
_SHAPES = ((8, 4, 8), (8, 4, 16), (16, 8, 16))
_EXECUTION_KEYS = frozenset(("validation", "primary", "cleanup", "complete"))
_MODEL_KEYS = frozenset(("status", "execution", "terminal"))
_MODEL_STATES = frozenset((
    "in_progress", "success", "runtime_error", "hidden_mismatch",
    "bridge_error", "bridge_mismatch", "output_mismatch",
    "resource_mismatch", "closed",
))


def _integer(value, name, *, maximum, minimum=0):
    if type(value) is not int:
        raise TypeError(f"{name} must be an exact int, excluding bool")
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if value > maximum:
        raise OverflowError(f"{name} exceeds {maximum}")
    return value


def _timeout(value):
    _integer(value, "timeout_ns", maximum=_UINT64_MAX)
    if value > _MAX_TIMEOUT_NS:
        raise ValueError("timeout_ns must be in 0..1_000_000_000 nanoseconds")
    return value


def _text(value, name):
    if type(value) is not str:
        raise TypeError(f"{name} must be an exact str")
    return value


@dataclass(frozen=True, slots=True)
class ExecutionStatus:
    """Separate native validation, execution, cleanup, and completion outcomes."""

    validation: str
    primary: int
    cleanup: int
    complete: bool

    def __post_init__(self):
        _text(self.validation, "validation")
        _integer(self.primary, "primary", maximum=_UINT32_MAX)
        _integer(self.cleanup, "cleanup", maximum=_UINT32_MAX)
        if type(self.complete) is not bool:
            raise TypeError("complete must be an exact bool")

    @property
    def ok(self):
        return (self.complete and self.validation == "success"
                and self.primary == 0 and self.cleanup == 0)

    def raise_for_status(self, operation=None):
        if not self.ok:
            raise BindingError(status=self, operation=operation)


@dataclass(frozen=True, slots=True)
class ModelStatus:
    """A model outcome retains inference validity independently of execution."""

    status: str
    execution: ExecutionStatus
    terminal: bool

    def __post_init__(self):
        _text(self.status, "status")
        if self.status not in _MODEL_STATES:
            raise ValueError(f"unknown model status: {self.status}")
        if type(self.execution) is not ExecutionStatus:
            raise TypeError("execution must be an ExecutionStatus")
        if type(self.terminal) is not bool:
            raise TypeError("terminal must be an exact bool")

    @property
    def ok(self):
        return self.terminal and self.status == "success" and self.execution.ok

    def raise_for_status(self, operation=None):
        if not self.ok:
            kind = None if not self.execution.ok else "model"
            if not self.terminal and self.execution.ok:
                kind = "incomplete"
            raise BindingError(status=self.execution, operation=operation,
                               model_status=self, kind=kind)


def _error_kind(status):
    if status is None:
        return "state"
    if status.validation != "success":
        return "validation"
    if status.primary != 0 and (status.complete or status.primary != _TIMEOUT):
        return "native"
    if status.cleanup != 0:
        return "cleanup"
    if not status.complete:
        return "incomplete"
    return "state"


class BindingError(RuntimeError):
    """A failed binding action, including any retained owner and native codes."""

    def __init__(self, message=None, *, status=None, operation=None, session=None,
                 model_status=None, kind=None, close_error=None):
        self.kind = kind if kind is not None else _error_kind(status)
        self.status = status
        self.operation = operation
        self.session = session
        self.model_status = model_status
        self.close_error = close_error
        if message is None:
            message = f"Vortex binding {self.kind} failure"
            if model_status is not None:
                message += f": model={model_status.status}, terminal={model_status.terminal}"
            if status is not None:
                message += (f": validation={status.validation}, primary={status.primary}, "
                            f"cleanup={status.cleanup}, complete={status.complete}")
            if status is not None and not status.complete:
                message += "; ownership is retained; retry a bounded wait or close"
        super().__init__(message)


_PENDING = ExecutionStatus("success", 0, 0, False)
_SUCCESS = ExecutionStatus("success", 0, 0, True)
_INITIAL_MODEL = ModelStatus("in_progress", _SUCCESS, False)


def _execution(raw):
    if type(raw) is not dict or raw.keys() != _EXECUTION_KEYS:
        raise BindingError("Native execution status has an invalid schema", kind="protocol")
    try:
        return ExecutionStatus(raw["validation"], raw["primary"],
                               raw["cleanup"], raw["complete"])
    except (TypeError, ValueError, OverflowError) as exc:
        raise BindingError("Native execution status has invalid fields", kind="protocol") from exc


def _model_status(raw):
    if type(raw) is not dict or raw.keys() != _MODEL_KEYS:
        raise BindingError("Native model status has an invalid schema", kind="protocol")
    try:
        return ModelStatus(raw["status"], _execution(raw["execution"]), raw["terminal"])
    except (TypeError, ValueError, OverflowError) as exc:
        raise BindingError("Native model status has invalid fields", kind="protocol") from exc


def _attach(exc, *, operation=None, session=None):
    # Retention in the session registry does not depend on allocating attributes.
    try:
        if operation is not None:
            exc.operation = operation
        if session is not None:
            exc.session = session
    except BaseException:
        pass


def _process_check(pid):
    if os.getpid() != pid:
        raise BindingError(
            "Inherited Vortex state cannot be used after fork; use spawn or exec "
            "and open a fresh qualified session", kind="process")


def _native_module():
    _process_check(_IMPORT_PID)
    try:
        return importlib.import_module("vortex_ai._native")
    except (ImportError, OSError, RuntimeError) as exc:
        raise BindingError(
            "The Vortex native extension is unavailable; install a compatible "
            "vortex-ai wheel and its matching qualified bundle. Import alone "
            "does not build or install runtime dependencies", kind="bundle") from exc


def build_info():
    """Return a copy of the extension's compiled identity without loading a runtime."""
    raw = _native_module().build_info()
    if (type(raw) is not dict
            or raw.keys() != {"binding_api", "bundle_sha256", "source_sha256"}
            or type(raw["binding_api"]) is not int or raw["binding_api"] != BINDING_API
            or type(raw["bundle_sha256"]) is not str
            or type(raw["source_sha256"]) is not str):
        raise BindingError("Native extension has an incompatible build identity", kind="protocol")
    return dict(raw)


def _cases(native):
    result = native.fixture_cases()
    if (type(result) is not tuple or len(result) != 10
            or any(type(item) is not str for item in result)
            or len(set(result)) != 10):
        raise BindingError("Native fixture inventory is invalid", kind="protocol")
    return result


def fixture_cases():
    """Return the ten compiled frozen case names without opening a runtime."""
    return _cases(_native_module())


def _byte_view(data, expected):
    if type(data) not in (bytes, bytearray, memoryview):
        raise TypeError("data must be exact bytes, bytearray, or memoryview storage")
    view = memoryview(data)
    try:
        if (view.ndim != 1 or view.itemsize != 1 or view.format not in ("B", "b", "c")
                or not view.c_contiguous or view.strides != (1,)
                or (view.suboffsets and any(offset >= 0 for offset in view.suboffsets))):
            raise ValueError("data must be one-dimensional contiguous byte storage with stride 1")
        if view.nbytes != expected:
            raise ValueError(f"data must contain exactly {expected} bytes, received {view.nbytes}")
        return view
    except BaseException:
        view.release()
        raise


@dataclass(frozen=True, slots=True, init=False, eq=False)
class Tensor:
    """Explicit little-endian 16-bit storage with immutable packed tensor metadata."""

    data: bytes | bytearray | memoryview
    dtype: str
    shape: tuple[int, int]
    layout: str
    strides: tuple[int, int]

    def __init__(self, data, *, dtype, shape, layout, strides=None):
        _text(dtype, "dtype")
        if dtype not in ("fp16", "bf16"):
            raise ValueError("dtype must be 'fp16' or 'bf16'")
        if type(shape) is not tuple:
            raise TypeError("shape must be an exact tuple of two integers")
        if len(shape) != 2:
            raise ValueError("shape must have exactly two dimensions")
        for dimension in shape:
            _integer(dimension, "shape dimension", maximum=_UINT32_MAX, minimum=1)
        _text(layout, "layout")
        if layout not in ("row_major", "column_major"):
            raise ValueError("layout must be 'row_major' or 'column_major'")
        expected = ((2 * shape[1], 2) if layout == "row_major"
                    else (2, 2 * shape[0]))
        if strides is not None:
            if type(strides) is not tuple:
                raise TypeError("strides must be an exact tuple of two integers")
            if len(strides) != 2:
                raise ValueError("strides must have exactly two dimensions")
            for stride in strides:
                _integer(stride, "byte stride", maximum=_UINT64_MAX, minimum=1)
            if strides != expected:
                raise ValueError(f"strides must match the packed byte strides {expected}")
        extent = 2 * shape[0] * shape[1]
        if extent > min(_UINT64_MAX, sys.maxsize):
            raise OverflowError("tensor byte extent exceeds the addressable buffer range")
        view = _byte_view(data, extent)
        view.release()
        object.__setattr__(self, "data", data)
        object.__setattr__(self, "dtype", dtype)
        object.__setattr__(self, "shape", shape)
        object.__setattr__(self, "layout", layout)
        object.__setattr__(self, "strides", expected)

    @property
    def nbytes(self):
        return 2 * self.shape[0] * self.shape[1]


class _Gate:
    __slots__ = ("_lock", "_pid")

    def __init__(self):
        self._lock = threading.RLock()
        self._pid = os.getpid()

    def __enter__(self):
        _process_check(self._pid)
        if self._lock._is_owned():
            raise BindingError("Concurrent or reentrant access to a Vortex owner is unsupported",
                               kind="reentrancy")
        try:
            if not self._lock.acquire(blocking=False):
                raise BindingError("Concurrent or reentrant access to a Vortex owner is unsupported",
                                   kind="reentrancy")
            return self
        except BaseException:
            # Ownership remains queryable if a signal interrupts acquire's return.
            if self._lock._is_owned():
                self._lock.release()
            raise

    def __exit__(self, *_):
        self._lock.release()


def _json_object(value):
    if type(value) is not str:
        raise BindingError("Native record must be a JSON string", kind="protocol")
    try:
        result = json.loads(value)
    except (ValueError, TypeError) as exc:
        raise BindingError("Native record is invalid JSON", kind="protocol") from exc
    if type(result) is not dict:
        raise BindingError("Native record must contain a JSON object", kind="protocol")
    return result


def _info_snapshot(raw):
    keys = {"format", "backend", "qualification_id", "source_revision",
            "bundle_sha256", "source_sha256", "libraries"}
    if type(raw) is not dict or raw.keys() != keys:
        raise BindingError("Native session identity has an invalid schema", kind="protocol")
    if any(type(raw[key]) is not str for key in keys - {"libraries"}):
        raise BindingError("Native session identity has invalid fields", kind="protocol")
    paths = raw["libraries"]
    if (type(paths) not in (tuple, list) or len(paths) != 5
            or any(type(path) is not str for path in paths)
            or raw["format"] not in ("fp16", "bf16")):
        raise BindingError("Native session identity has invalid runtime metadata", kind="protocol")
    result = dict(raw)
    result["libraries"] = tuple(paths)
    return MappingProxyType(result)


class _ContextOwner:
    __slots__ = ()

    def __enter__(self):
        with self._gate:
            if self._close_status is not None:
                raise BindingError("A closed Vortex owner cannot enter a context", kind="state")
        return self

    def __exit__(self, exc_type, exc, traceback):
        operation = None if type(self) is Session else self
        session = self if operation is None else self._session_ref()
        try:
            result = self.close()
            if not result.ok:
                raise BindingError(status=result, operation=operation, session=session)
            if type(self) is ModelOperation and self.status.status != "closed":
                self.status.raise_for_status(self)
        except BaseException as close_error:
            if isinstance(close_error, BindingError):
                error = close_error
                _attach(error, operation=operation, session=session)
            else:
                error = BindingError("The bounded context close did not finish successfully",
                                     status=self._last_execution, operation=operation,
                                     session=session, kind="cleanup", close_error=close_error)
            if exc is not None:
                raise error from exc
            if error is close_error:
                raise
            raise error from close_error
        return False


class Session(_ContextOwner):
    """A qualified native session; opening never accepts caller provenance flags."""

    __slots__ = ("_native", "_handle", "_gate", "_pending", "_info", "_closing",
                 "_close_status", "_last_execution", "_raw_status", "__weakref__")

    def __init__(self):
        raise TypeError("Use Session.open(bundle_root) to create a qualified session")

    @classmethod
    def open(cls, bundle_root):
        if cls is not Session:
            raise TypeError("Session subclasses are unsupported")
        _text(bundle_root, "bundle_root")
        if not bundle_root or "\x00" in bundle_root:
            raise ValueError("bundle_root must be a nonempty path without NUL characters")
        result = object.__new__(cls)
        result._native = _native_module()
        result._handle = None
        result._gate = _Gate()
        result._pending = {}
        result._info = MappingProxyType({})
        result._closing = False
        result._close_status = None
        result._last_execution = _PENDING
        result._raw_status = None
        try:
            with result._gate:
                try:
                    opened = result._native.session_open(bundle_root)
                except BlockingIOError as cause:
                    raise BindingError(str(cause), kind="state", session=result) from cause
                except (ValueError, OSError, RuntimeError) as cause:
                    raise BindingError(
                        "Could not open the qualified Vortex bundle: " + str(cause)
                        + ". Install a wheel built for this exact bundle and keep its "
                        "matched runtime, module, and receipt files together",
                        kind="bundle", session=result) from cause
                if type(opened) is not tuple or len(opened) != 2:
                    raise BindingError("Native session_open returned an invalid result", kind="protocol")
                result._handle, result._raw_status = opened
                result._last_execution = _execution(result._raw_status)
                if not result._last_execution.ok:
                    raise BindingError("Qualified Vortex session creation failed",
                                       status=result._last_execution, session=result)
                if result._handle is None:
                    raise BindingError("Native session creation returned no owner", kind="protocol")
                result._info = _info_snapshot(result._native.session_info(result._handle))
        except BaseException as error:
            _attach(error, session=result)
            raise
        return result

    @property
    def info(self):
        return self._info

    @property
    def status(self):
        return self._last_execution if self._raw_status is None else _execution(self._raw_status)

    def _ensure_open(self):
        if self._closing or self._handle is None:
            raise BindingError("The session is closing or closed; new work cannot be submitted",
                               status=self._last_execution, session=self, kind="state")

    def pending_operations(self):
        """Return retained owners, including submissions interrupted before returning."""
        with self._gate:
            return tuple(self._pending.values())

    def submit(self, a, b, *, poison=_DEFAULT_POISON):
        if type(a) is not Tensor or type(b) is not Tensor:
            raise TypeError("a and b must be Tensor objects; implicit conversion is unsupported")
        _integer(poison, "poison", maximum=_UINT32_MAX)
        with self._gate:
            self._ensure_open()
            if a.dtype != b.dtype or a.dtype != self._info["format"]:
                raise ValueError("both tensor dtypes must match the qualified session format")
            if a.layout != "row_major" or b.layout != "column_major":
                raise ValueError("A must be row_major and B must be column_major")
            m, k = a.shape
            if b.shape[0] != k:
                raise ValueError("A and B must have the same K dimension")
            n = b.shape[1]
            if (m, n, k) not in _SHAPES:
                raise ValueError(f"unsupported (M, N, K) signature: {(m, n, k)}")
            a_view = _byte_view(a.data, a.nbytes)
            try:
                b_view = _byte_view(b.data, b.nbytes)
                try:
                    operation = Operation._new(self, m * n * 4)
                    self._pending[id(operation)] = operation
                    try:
                        raw = self._native.submit_into(self._handle, operation._handle,
                                                       m, n, k, a_view, b_view, poison)
                        operation._store(raw)
                    except BlockingIOError as cause:
                        raise BindingError(str(cause), kind="state", operation=operation,
                                           session=self) from cause
                    except BaseException as error:
                        _attach(error, operation=operation, session=self)
                        raise
                    return operation
                finally:
                    b_view.release()
            finally:
                a_view.release()

    def model(self, case_id, *, poison=_DEFAULT_POISON):
        _text(case_id, "case_id")
        _integer(poison, "poison", maximum=_UINT32_MAX)
        with self._gate:
            self._ensure_open()
            if case_id not in _cases(self._native):
                raise ValueError("case_id must name one of the compiled frozen fixture cases")
            if not case_id.startswith(self._info["format"] + "-"):
                raise ValueError("the model case dtype must match the qualified session format")
            operation = ModelOperation._new(self, case_id, poison)
            self._pending[id(operation)] = operation
            try:
                raw = self._native.model_create_into(self._handle, operation._handle, case_id, poison)
                operation._creation_raw = raw
                execution = _execution(raw)
                operation._last_execution = execution
                operation._model_status = ModelStatus(
                    "in_progress" if execution.ok else "runtime_error", execution, not execution.ok)
            except BlockingIOError as cause:
                raise BindingError(str(cause), kind="state", operation=operation,
                                   session=self) from cause
            except BaseException as error:
                _attach(error, operation=operation, session=self)
                raise
            return operation

    def memory_info(self):
        """Return (code, free_bytes, used_bytes), raising with code on native failure."""
        with self._gate:
            if self._closing or self._handle is None or self._close_status is not None:
                raise BindingError("Memory information requires an open native session",
                                   status=self._last_execution, session=self, kind="state")
            try:
                result = self._native.session_memory_info(self._handle)
            except BlockingIOError as cause:
                raise BindingError(str(cause), kind="state", session=self) from cause
            if (type(result) is not tuple or len(result) != 3
                    or any(type(value) is not int or value < 0 for value in result)):
                raise BindingError("Native memory information has an invalid schema", kind="protocol")
            if result[0] != 0:
                raise BindingError("Native memory information is unavailable",
                                   status=ExecutionStatus("success", result[0], 0, True),
                                   session=self, kind="native")
            return result

    def close(self):
        with self._gate:
            self._closing = True
            if self._close_status is not None:
                return self._close_status
            if self._handle is None:
                if not self._last_execution.complete:
                    self._last_execution = _SUCCESS
                    self._raw_status = None
                self._close_status = self._last_execution
                return self._last_execution
            try:
                self._raw_status = self._native.session_close(self._handle)
                result = _execution(self._raw_status)
                self._last_execution = result
                if result.complete:
                    self._close_status = result
                return result
            except BaseException as error:
                _attach(error, session=self)
                raise


class _OperationOwner(_ContextOwner):
    __slots__ = ("_native", "_handle", "_gate", "_session_ref", "_close_status",
                 "_last_execution", "__weakref__")

    def __init__(self):
        raise TypeError("Operations are created by Session.submit() or Session.model()")

    def _unregister(self):
        session = self._session_ref()
        if session is not None:
            session._pending.pop(id(self), None)

    def _state_call(self, function, *args):
        try:
            return function(self._handle, *args)
        except BlockingIOError as cause:
            raise BindingError(str(cause), kind="state", status=self._last_execution,
                               operation=self, session=self._session_ref()) from cause

    def output_words(self):
        """Return unsigned raw FP32 words decoded explicitly as little endian."""
        data = self.output_bytes()
        return struct.unpack(f"<{len(data) // 4}I", data)

    def _bytes(self, result, expected):
        if type(result) is not bytes or len(result) != expected or expected == 0:
            raise BindingError("Native output has an invalid type or byte extent",
                               status=self._last_execution, operation=self, kind="protocol")
        return result


class Operation(_OperationOwner):
    """Owned matmul work; timeouts retain the owner and never cancel execution."""

    __slots__ = ("_raw_status", "_expected_bytes")

    @classmethod
    def _new(cls, session, expected_bytes):
        result = object.__new__(cls)
        result._native = session._native
        result._gate = session._gate
        result._session_ref = weakref.ref(session)
        result._close_status = None
        result._last_execution = _PENDING
        result._raw_status = None
        result._expected_bytes = expected_bytes
        result._handle = result._native.operation_new()
        return result

    @property
    def status(self):
        return self._last_execution if self._raw_status is None else _execution(self._raw_status)

    def _store(self, raw):
        self._raw_status = raw
        self._last_execution = _execution(raw)
        return self._last_execution

    def wait(self, timeout_ns=_DEFAULT_TIMEOUT_NS):
        _timeout(timeout_ns)
        with self._gate:
            if self._close_status is not None:
                return self._close_status
            try:
                return self._store(self._state_call(self._native.operation_wait, timeout_ns))
            except BaseException as error:
                _attach(error, operation=self, session=self._session_ref())
                raise

    def close(self, timeout_ns=_DEFAULT_TIMEOUT_NS):
        _timeout(timeout_ns)
        with self._gate:
            try:
                if self._close_status is None:
                    result = self._store(self._state_call(self._native.operation_close, timeout_ns))
                    if result.complete:
                        self._close_status = result
                if self._close_status is not None:
                    self._unregister()
                    return self._close_status
                return self._last_execution
            except BaseException as error:
                _attach(error, operation=self, session=self._session_ref())
                raise

    def output_bytes(self):
        with self._gate:
            self.status.raise_for_status(self)
            try:
                result = self._native.operation_output(self._handle)
            except RuntimeError as cause:
                raise BindingError("The native operation has no complete successful output",
                                   status=self._last_execution, operation=self, kind="state") from cause
            return self._bytes(result, self._expected_bytes)

    def trace(self):
        """Return a detached diagnostic snapshot, including validity and native status."""
        with self._gate:
            return _json_object(self._state_call(self._native.operation_trace))


class ModelOperation(_OperationOwner):
    """One frozen model case; advance timeout applies separately to each native wait."""

    __slots__ = ("_model_status", "_raw_model_status", "_creation_raw", "_case_id",
                 "_poison", "_refresh_after_close")

    @classmethod
    def _new(cls, session, case_id, poison):
        result = object.__new__(cls)
        result._native = session._native
        result._gate = session._gate
        result._session_ref = weakref.ref(session)
        result._close_status = None
        result._last_execution = _PENDING
        result._model_status = _INITIAL_MODEL
        result._raw_model_status = None
        result._creation_raw = None
        result._case_id = case_id
        result._poison = poison
        result._refresh_after_close = False
        result._handle = result._native.model_new()
        return result

    @property
    def status(self):
        if self._refresh_after_close:
            raise BindingError("Model close status publication was interrupted; retry close() "
                               "or advance(0) to recover the native outcome",
                               status=self._last_execution, operation=self, kind="state")
        if self._raw_model_status is not None:
            return _model_status(self._raw_model_status)
        if self._creation_raw is not None:
            execution = _execution(self._creation_raw)
            return ModelStatus("in_progress" if execution.ok else "runtime_error",
                               execution, not execution.ok)
        return self._model_status

    def _store_model(self, raw):
        self._raw_model_status = raw
        result = _model_status(raw)
        self._model_status = result
        self._last_execution = result.execution
        self._refresh_after_close = False
        return result

    def advance(self, timeout_ns=_DEFAULT_TIMEOUT_NS):
        _timeout(timeout_ns)
        with self._gate:
            try:
                return self._store_model(self._state_call(self._native.model_advance, timeout_ns))
            except BaseException as error:
                _attach(error, operation=self, session=self._session_ref())
                raise

    def close(self, timeout_ns=_DEFAULT_TIMEOUT_NS):
        _timeout(timeout_ns)
        with self._gate:
            try:
                if self._close_status is None:
                    self._refresh_after_close = True
                    raw = self._state_call(self._native.model_close, timeout_ns)
                    result = _execution(raw)
                    self._last_execution = result
                    if result.complete:
                        self._close_status = result
                else:
                    result = self._close_status
                if self._refresh_after_close:
                    # A closing native model returns its stored result without advancing work.
                    self._store_model(self._state_call(self._native.model_advance, 0))
                if self._close_status is not None:
                    self._unregister()
                return result
            except BaseException as error:
                _attach(error, operation=self, session=self._session_ref())
                raise

    def output_bytes(self):
        with self._gate:
            self.status.raise_for_status(self)
            try:
                result = self._native.model_output(self._handle)
            except RuntimeError as cause:
                raise BindingError("Successful model output requires completed explicit close, "
                                   "successful cleanup, and valid resource accounting",
                                   status=self._last_execution, operation=self, kind="state") from cause
            return self._bytes(result, 16 * 4 * 4)

    def trace(self):
        """Return actual diagnostic observations; a valid array need not have matched."""
        with self._gate:
            return _json_object(self._state_call(self._native.model_trace))

    def record(self, iteration=0):
        """Return the P04 record envelope, which may describe incomplete or failed work."""
        _integer(iteration, "iteration", maximum=_UINT32_MAX)
        if iteration not in (0, 1):
            raise ValueError("iteration must be 0 or 1")
        if self._poison != (_DEFAULT_POISON, 0xDEADBEEF)[iteration]:
            raise ValueError("iteration must match the model's frozen output poison")
        with self._gate:
            return _json_object(self._state_call(self._native.model_record, iteration))
