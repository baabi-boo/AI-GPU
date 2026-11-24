# SPDX-License-Identifier: Apache-2.0
"""Host-only facade mocks; no extension, native numerical, or GPU qualification."""

import array
import dataclasses
import gc
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import threading
import types
import unittest
from unittest import mock
import weakref


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "python/vortex_ai"
CASES = tuple(f"{dtype}-{case}" for dtype in ("fp16", "bf16") for case in (
    "seeded_dense", "negated_dense", "zero", "signed_basis", "split_boundary"))
SIGNATURES = ((8, 4, 8), (8, 4, 16), (16, 8, 16))


def status(primary=0, cleanup=0, complete=True, validation="success"):
    return dict(validation=validation, primary=primary, cleanup=cleanup, complete=complete)


def model_status(name="in_progress", *, execution=None, terminal=False):
    return dict(status=name, execution=status() if execution is None else execution,
                terminal=terminal)


class NativeMock(types.ModuleType):
    """Scripted host responses exercise Python ownership, never native computation."""

    def __init__(self):
        super().__init__("vortex_ai._native")
        self.format = "fp16"
        self.next_submit = self.next_create = self.next_close = None
        self.session_cleanup = 0
        self.memory_result = (0, 100, 0)
        self.on_submit = None
        self.calls = []

    def build_info(self):
        return dict(binding_api=1, bundle_sha256="a" * 64, source_sha256="b" * 64)

    def fixture_cases(self):
        return CASES

    def session_open(self, root):
        self.calls.append(("session_open", root))
        return ({"ops": [], "closed": False}, status())

    def session_info(self, cap):
        return dict(format=self.format, backend="simx", qualification_id="c" * 64,
                    source_revision="d" * 40, bundle_sha256="a" * 64,
                    source_sha256="b" * 64, libraries=["/mock/lib" + str(i) for i in range(5)])

    def session_memory_info(self, cap):
        self.calls.append("memory_info")
        return self.memory_result

    def session_close(self, cap):
        self.calls.append("session_close")
        if any(not operation["closed"] for operation in cap["ops"]):
            return status(primary=7, complete=False)
        cap["closed"] = True
        result = status(cleanup=self.session_cleanup)
        self.session_cleanup = 0
        return result

    def operation_new(self):
        self.calls.append("operation_new")
        return {"closed": False, "status": status(complete=False)}

    def submit_into(self, session, operation, m, n, k, a, b, poison):
        if type(a) is not memoryview or type(b) is not memoryview:
            raise AssertionError("the facade must hold fresh buffer views during submission")
        self.calls.append(("submit", m, n, k, poison))
        operation.update(a=bytes(a), b=bytes(b),
                         output=struct.pack("<" + "I" * (m * n), *range(m * n)))
        session["ops"].append(operation)
        if self.on_submit is not None:
            self.on_submit()
        fault, self.next_submit = self.next_submit, None
        if isinstance(fault, BaseException):
            operation["status"] = status(primary=6, complete=False)
            raise fault
        if fault is not None:
            operation["status"] = fault
        return operation["status"]

    def operation_wait(self, cap, timeout):
        self.calls.append(("wait", timeout))
        if timeout == 0:
            return status(primary=cap["status"]["primary"] or 7, complete=False)
        primary = cap["status"]["primary"]
        cap["status"] = status(primary=0 if primary == 7 else primary)
        return cap["status"]

    def operation_close(self, cap, timeout):
        self.calls.append(("operation_close", timeout))
        result, self.next_close = self.next_close, None
        if result is None:
            primary = cap["status"]["primary"]
            result = status(primary=0 if primary == 7 else primary)
        cap["status"] = result
        if result["complete"]:
            cap["closed"] = True
        return result

    def operation_output(self, cap):
        self.calls.append("operation_output")
        return cap["output"]

    def operation_trace(self, cap):
        return json.dumps({"a": list(cap["a"]), "complete": cap["status"]["complete"]})

    def model_new(self):
        self.calls.append("model_new")
        return {"closed": False, "model_status": model_status()}

    def model_create_into(self, session, cap, case, poison):
        self.calls.append(("model_create", case, poison))
        cap.update(case=case, poison=poison)
        fault, self.next_create = self.next_create, None
        if isinstance(fault, BaseException):
            cap["model_status"] = model_status(
                "runtime_error", execution=status(primary=6), terminal=True)
            raise fault
        result = status() if fault is None else fault
        if result != status():
            cap["model_status"] = model_status("runtime_error", execution=result, terminal=True)
        return result

    def model_advance(self, cap, timeout):
        self.calls.append(("model_advance", timeout))
        if not cap["closed"] and not cap["model_status"]["terminal"]:
            cap["model_status"] = model_status(
                "success" if timeout else "in_progress",
                execution=status(complete=bool(timeout)), terminal=bool(timeout))
        return cap["model_status"]

    def model_close(self, cap, timeout):
        self.calls.append(("model_close", timeout))
        cap["closed"] = True
        if not cap["model_status"]["terminal"]:
            cap["model_status"] = model_status("closed", terminal=True)
        return cap["model_status"]["execution"]

    def model_output(self, cap):
        self.calls.append("model_output")
        if not cap["closed"]:
            raise RuntimeError("owner not closed")
        return bytes(256)

    def model_trace(self, cap):
        return json.dumps({"result": cap["model_status"], "owner_closed": cap["closed"]})

    def model_record(self, cap, iteration):
        self.calls.append(("model_record", iteration))
        return json.dumps({"iteration": iteration, "trace": {"result": cap["model_status"]}})


class PythonImportTests(unittest.TestCase):
    def test_package_import_does_not_request_the_extension_or_bundle(self):
        code = """
import importlib.abc
import sys

class RejectNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in ('vortex_ai._native', 'vortex_ai._bundle'):
            raise AssertionError('eager import: ' + fullname)

sys.path.insert(0, sys.argv[1])
sys.meta_path.insert(0, RejectNative())
import vortex_ai
assert vortex_ai.BINDING_API == 1
assert vortex_ai.__version__ == '0.1.0'
assert 'vortex_ai._native' not in sys.modules
assert 'vortex_ai._bundle' not in sys.modules
print('pure Python import')
"""
        result = subprocess.run([sys.executable, "-I", "-c", code, str(PACKAGE.parent)],
                                cwd=ROOT, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "pure Python import\n")


class PythonApiMockTests(unittest.TestCase):
    def setUp(self):
        self.saved_modules = {name: module for name, module in tuple(sys.modules.items())
                              if name == "vortex_ai" or name.startswith("vortex_ai.")}
        self.addCleanup(self.restore_modules)
        for name in self.saved_modules:
            del sys.modules[name]
        spec = importlib.util.spec_from_file_location(
            "vortex_ai", PACKAGE / "__init__.py", submodule_search_locations=[str(PACKAGE)])
        self.api = importlib.util.module_from_spec(spec)
        sys.modules["vortex_ai"] = self.api
        spec.loader.exec_module(self.api)
        self.impl = sys.modules["vortex_ai._api"]
        self.assertNotIn("vortex_ai._native", sys.modules)
        self.native = NativeMock()
        sys.modules["vortex_ai._native"] = self.native

    def restore_modules(self):
        for name in tuple(sys.modules):
            if name == "vortex_ai" or name.startswith("vortex_ai."):
                del sys.modules[name]
        sys.modules.update(self.saved_modules)

    def tensors(self, dtype="fp16", signature=(8, 4, 8)):
        m, n, k = signature
        return (self.api.Tensor(bytes(2 * m * k), dtype=dtype, shape=(m, k), layout="row_major"),
                self.api.Tensor(bytes(2 * k * n), dtype=dtype, shape=(k, n), layout="column_major"))

    def session(self, dtype="fp16"):
        self.native.format = dtype
        return self.api.Session.open("/mock/bundle")

    def test_identity_snapshots_are_detached_and_read_only(self):
        self.assertEqual(self.api.__version__, "0.1.0")
        self.assertEqual(self.api.BINDING_API, 1)
        self.assertEqual(self.api.fixture_cases(), CASES)
        raw = self.native.build_info()
        with mock.patch.object(self.native, "build_info", return_value=raw):
            info = self.api.build_info()
        info["bundle_sha256"] = "modified"
        self.assertEqual(raw["bundle_sha256"], "a" * 64)
        raw = self.native.session_info(None)
        with mock.patch.object(self.native, "session_info", return_value=raw):
            session = self.session()
        raw["format"] = "bf16"
        raw["libraries"][0] = "changed"
        self.assertEqual(session.info["format"], "fp16")
        self.assertEqual(session.info["libraries"][0], "/mock/lib0")
        self.assertIs(type(session.info["libraries"]), tuple)
        with self.assertRaises(TypeError):
            session.info["format"] = "bf16"
        self.assertTrue(session.close().ok)

    def test_identity_and_fixture_schemas_reject_malformed_native_results(self):
        for value in (None, {}, dict(self.native.build_info(), binding_api=True),
                      dict(self.native.build_info(), binding_api=2),
                      dict(self.native.build_info(), source_sha256=1)):
            with self.subTest(identity=value), mock.patch.object(
                    self.native, "build_info", return_value=value):
                with self.assertRaises(self.api.BindingError) as caught:
                    self.api.build_info()
                self.assertEqual(caught.exception.kind, "protocol")
        for value in (list(CASES), CASES[:-1], CASES[:-1] + (CASES[0],), CASES[:-1] + (1,)):
            with self.subTest(cases=value), mock.patch.object(
                    self.native, "fixture_cases", return_value=value):
                with self.assertRaises(self.api.BindingError) as caught:
                    self.api.fixture_cases()
                self.assertEqual(caught.exception.kind, "protocol")

    def test_tensor_metadata_is_immutable_and_strict(self):
        a, b = self.tensors()
        self.assertEqual((a.strides, b.strides, a.nbytes, b.nbytes),
                         ((16, 2), (2, 16), 128, 64))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            a.dtype = "bf16"
        invalid = (({"dtype": "fp32"}, ValueError), ({"dtype": None}, TypeError),
                   ({"shape": [8, 8]}, TypeError), ({"shape": (True, 8)}, TypeError),
                   ({"shape": (8,)}, ValueError), ({"shape": (0, 8)}, ValueError),
                   ({"shape": (-1, 8)}, ValueError), ({"shape": (8.0, 8)}, TypeError),
                   ({"shape": (2**32, 8)}, OverflowError),
                   ({"shape": (2**32 - 1, 2**32 - 1)}, OverflowError),
                   ({"strides": [16, 2]}, TypeError), ({"strides": (16,)}, ValueError),
                   ({"strides": (0, 2)}, ValueError), ({"strides": (18, 2)}, ValueError),
                   ({"strides": (False, 2)}, TypeError),
                   ({"strides": (2**64, 2)}, OverflowError),
                   ({"layout": "C"}, ValueError), ({"layout": None}, TypeError))
        for change, error in invalid:
            arguments = dict(dtype="fp16", shape=(8, 8), layout="row_major")
            arguments.update(change)
            with self.subTest(change=change), self.assertRaises(error):
                self.api.Tensor(bytes(128), **arguments)

    def test_tensor_accepts_only_exact_packed_byte_storage(self):
        arguments = dict(dtype="fp16", shape=(8, 8), layout="row_major", strides=(16, 2))
        for data in (bytes(128), bytearray(128), memoryview(bytes(128)),
                     memoryview(bytes(128)).cast("b"), memoryview(bytes(128)).cast("c")):
            with self.subTest(format=type(data)):
                self.assertIs(self.api.Tensor(data, **arguments).data, data)
        for data in (bytes(126), bytes(130), memoryview(bytes(256))[::2],
                     memoryview(bytes(128))[::-1], memoryview(bytes(128)).cast("B", (8, 16)),
                     memoryview(array.array("H", [0] * 64))):
            with self.subTest(data=repr(data)), self.assertRaises(ValueError):
                self.api.Tensor(data, **arguments)
        class BytesSubclass(bytes):
            pass
        for data in (BytesSubclass(128), array.array("B", [0] * 128), [0] * 128, None):
            with self.subTest(data=type(data)), self.assertRaises(TypeError):
                self.api.Tensor(data, **arguments)
        released = memoryview(bytes(128))
        released.release()
        with self.assertRaises(ValueError):
            self.api.Tensor(released, **arguments)

    def test_exact_integer_and_string_subclasses_are_rejected(self):
        class IntSubclass(int):
            pass
        class StrSubclass(str):
            pass
        class TupleSubclass(tuple):
            pass
        for change in ({"shape": (IntSubclass(8), 8)}, {"dtype": StrSubclass("fp16")},
                       {"layout": StrSubclass("row_major")},
                       {"shape": TupleSubclass((8, 8))},
                       {"strides": (IntSubclass(16), 2)}):
            arguments = dict(dtype="fp16", shape=(8, 8), layout="row_major")
            arguments.update(change)
            with self.subTest(change=change), self.assertRaises(TypeError):
                self.api.Tensor(bytes(128), **arguments)

    def test_all_six_supported_signatures_dispatch_exact_metadata(self):
        for dtype in ("fp16", "bf16"):
            session = self.session(dtype)
            for signature in SIGNATURES:
                with self.subTest(dtype=dtype, signature=signature):
                    operation = session.submit(*self.tensors(dtype, signature), poison=0xDEADBEEF)
                    self.assertIn(("submit", *signature, 0xDEADBEEF), self.native.calls)
                    self.assertTrue(operation.wait().ok)
                    self.assertEqual(len(operation.output_bytes()), signature[0] * signature[1] * 4)
                    operation.close()
            self.assertEqual(session.pending_operations(), ())
            self.assertTrue(session.close().ok)

    def test_invalid_submissions_do_not_allocate_or_dispatch(self):
        session = self.session()
        a, b = self.tensors()
        make = lambda shape, layout, dtype="fp16": self.api.Tensor(
            bytes(2 * shape[0] * shape[1]), shape=shape, layout=layout, dtype=dtype)
        invalid = ((None, b, TypeError), (a.data, b, TypeError),
                   (*self.tensors("bf16"), ValueError),
                   (make((8, 8), "row_major", "bf16"), b, ValueError),
                   (make((8, 8), "column_major"), b, ValueError),
                   (a, make((8, 4), "row_major"), ValueError),
                   (a, make((16, 4), "column_major"), ValueError),
                   (make((4, 8), "row_major"), b, ValueError))
        for left, right, error in invalid:
            with self.subTest(left=left, right=right), self.assertRaises(error):
                session.submit(left, right)
        for poison, error in ((True, TypeError), (1.0, TypeError), (-1, ValueError),
                              (2**32, OverflowError)):
            with self.subTest(poison=poison), self.assertRaises(error):
                session.submit(a, b, poison=poison)
        self.assertNotIn("operation_new", self.native.calls)
        self.assertEqual(session.pending_operations(), ())

    def test_mock_copy_releases_views_and_keeps_output_after_explicit_close(self):
        session = self.session()
        left, right = bytearray(128), bytearray(64)
        a = self.api.Tensor(left, dtype="fp16", shape=(8, 8), layout="row_major")
        b = self.api.Tensor(right, dtype="fp16", shape=(8, 4), layout="column_major")
        def during_submit():
            for data in (left, right):
                with self.assertRaises(BufferError):
                    data.append(1)
        self.native.on_submit = during_submit
        operation = session.submit(a, b)
        left[0] = right[0] = 99
        left.append(1)
        right.append(1)
        self.assertEqual(operation.trace()["a"][0], 0)
        self.assertEqual(operation._handle["b"][0], 0)
        self.assertEqual(session.pending_operations(), (operation,))
        with self.assertRaises(self.api.BindingError) as caught:
            operation.output_bytes()
        self.assertIs(caught.exception.operation, operation)
        self.assertNotIn("operation_output", self.native.calls)
        self.assertFalse(operation.wait(0).ok)
        self.assertEqual(operation.status.primary, 7)
        self.assertTrue(operation.wait(1).ok)
        self.assertEqual(operation.output_words(), tuple(range(32)))
        output = operation.output_bytes()
        self.assertTrue(operation.close().ok)
        self.assertEqual(session.pending_operations(), ())
        self.assertEqual(operation.output_bytes(), output)
        self.assertTrue(session.close().ok)

    def test_resized_or_released_inputs_fail_before_owner_creation(self):
        session = self.session()
        for index in (0, 1):
            left, right = bytearray(128), bytearray(64)
            a = self.api.Tensor(left, dtype="fp16", shape=(8, 8), layout="row_major")
            b = self.api.Tensor(right, dtype="fp16", shape=(8, 4), layout="column_major")
            (left, right)[index].append(1)
            with self.subTest(index=index), self.assertRaises(ValueError):
                session.submit(a, b)
            left.append(2)
            right.append(2)
        view = memoryview(bytes(128))
        a = self.api.Tensor(view, dtype="fp16", shape=(8, 8), layout="row_major")
        view.release()
        with self.assertRaises(ValueError):
            session.submit(a, self.tensors()[1])
        self.assertNotIn("operation_new", self.native.calls)
        self.assertEqual(session.pending_operations(), ())

    def test_native_failure_returns_retained_owner_and_separate_status(self):
        session = self.session()
        self.native.next_submit = status(primary=6, complete=False)
        operation = session.submit(*self.tensors())
        self.assertEqual(operation.status.primary, 6)
        self.assertFalse(operation.status.complete)
        self.assertEqual(operation.wait(0).primary, 6)
        self.assertEqual(session.pending_operations(), (operation,))
        self.assertEqual(operation.close().primary, 6)
        self.assertEqual(session.pending_operations(), ())
        with self.assertRaises(self.api.BindingError) as caught:
            operation.status.raise_for_status(operation)
        self.assertIs(caught.exception.operation, operation)
        self.assertEqual(caught.exception.kind, "native")

    def test_submit_interruptions_retain_owner_and_release_both_views(self):
        class UnattachableMemoryError(MemoryError):
            def __setattr__(self, name, value):
                raise MemoryError("exception attribute allocation failed")
        for error in (MemoryError("publication"), KeyboardInterrupt("signal"),
                      UnattachableMemoryError("publication and attachment")):
            with self.subTest(error=type(error)):
                session = self.session()
                left, right = bytearray(128), bytearray(64)
                a = self.api.Tensor(left, dtype="fp16", shape=(8, 8), layout="row_major")
                b = self.api.Tensor(right, dtype="fp16", shape=(8, 4), layout="column_major")
                self.native.next_submit = error
                with self.assertRaises(type(error)) as caught:
                    session.submit(a, b)
                self.assertIs(caught.exception, error)
                left.append(1)
                right.append(1)
                (operation,) = session.pending_operations()
                if type(error) is not UnattachableMemoryError:
                    self.assertIs(error.operation, operation)
                    self.assertIs(error.session, session)
                else:
                    self.assertFalse(hasattr(error, "operation"))
                self.assertEqual(operation.close().primary, 6)
                self.assertEqual(session.pending_operations(), ())
                self.assertTrue(session.close().ok)

    def test_empty_handle_allocation_failure_never_submits_work(self):
        session = self.session()
        for method, action in (("operation_new", lambda: session.submit(*self.tensors())),
                               ("model_new", lambda: session.model(CASES[0]))):
            with self.subTest(method=method), mock.patch.object(
                    self.native, method, side_effect=MemoryError("empty owner")):
                with self.assertRaises(MemoryError):
                    action()
                self.assertEqual(session.pending_operations(), ())
        self.assertFalse(any(type(call) is tuple and call[0] in ("submit", "model_create")
                             for call in self.native.calls))

    def test_wait_and_close_publication_interruptions_are_recoverable(self):
        session = self.session()
        for method, error in (("operation_wait", KeyboardInterrupt("wait publication")),
                              ("operation_close", MemoryError("close publication"))):
            with self.subTest(method=method):
                operation = session.submit(*self.tensors())
                original = getattr(self.native, method)
                def interrupted(cap, timeout):
                    original(cap, timeout)
                    raise error
                with mock.patch.object(self.native, method, side_effect=interrupted):
                    with self.assertRaises(type(error)) as caught:
                        (operation.wait if method == "operation_wait" else operation.close)()
                self.assertIs(caught.exception.operation, operation)
                self.assertEqual(session.pending_operations(), (operation,))
                self.assertTrue(operation.close().ok)
                self.assertEqual(session.pending_operations(), ())

    def test_close_timeouts_retry_and_terminal_cleanup_failure_is_sticky(self):
        session = self.session()
        operation = session.submit(*self.tensors())
        self.native.next_close = status(primary=7, complete=False)
        self.assertFalse(operation.close(0).complete)
        self.assertEqual(session.pending_operations(), (operation,))
        self.native.next_close = status(cleanup=6)
        failure = operation.close()
        self.assertEqual(failure.cleanup, 6)
        self.assertEqual(session.pending_operations(), ())
        calls = tuple(self.native.calls)
        self.assertIs(operation.close(), failure)
        self.assertIs(operation.wait(), failure)
        self.assertEqual(tuple(self.native.calls), calls)
        with self.assertRaises(self.api.BindingError) as caught:
            operation.output_bytes()
        self.assertEqual(caught.exception.kind, "cleanup")
        self.native.session_cleanup = 8
        failure = session.close()
        self.assertEqual(failure.cleanup, 8)
        self.assertIs(session.close(), failure)
        self.assertEqual(self.native.calls.count("session_close"), 1)

    def test_session_close_never_drains_and_operations_can_outlive_session(self):
        session = self.session()
        operation = session.submit(*self.tensors())
        self.assertFalse(session.close().complete)
        self.assertNotIn(("wait", 100_000_000), self.native.calls)
        self.assertNotIn(("operation_close", 100_000_000), self.native.calls)
        for action in (lambda: session.submit(*self.tensors()), lambda: session.model(CASES[0])):
            with self.assertRaises(self.api.BindingError) as caught:
                action()
            self.assertEqual(caught.exception.kind, "state")
        reference = weakref.ref(session)
        del session, action, caught
        gc.collect()
        self.assertIsNone(reference())
        self.assertTrue(operation.wait().ok)
        self.assertTrue(operation.close().ok)

    def test_reentry_and_inherited_process_guards_reject_before_native_access(self):
        session = self.session()
        self.native.on_submit = session.close
        with self.assertRaises(self.api.BindingError) as caught:
            session.submit(*self.tensors())
        self.assertEqual(caught.exception.kind, "reentrancy")
        self.native.on_submit = None
        session.pending_operations()[0].close()
        pid = session._gate._pid
        session._gate._pid = pid + 1
        with self.assertRaises(self.api.BindingError) as caught:
            session.close()
        self.assertEqual(caught.exception.kind, "process")
        session._gate._pid = pid
        self.assertTrue(session.close().ok)
        with mock.patch.object(self.impl, "_IMPORT_PID", pid + 1):
            with self.assertRaises(self.api.BindingError) as caught:
                self.api.build_info()
            self.assertEqual(caught.exception.kind, "process")

    def test_concurrent_facade_access_fails_without_waiting_for_the_owner(self):
        session = self.session()
        entered, release = threading.Event(), threading.Event()
        def hold_gate():
            with session._gate:
                entered.set()
                release.wait(2)
        worker = threading.Thread(target=hold_gate, daemon=True)
        worker.start()
        try:
            self.assertTrue(entered.wait(1), "worker did not acquire the facade guard")
            with self.assertRaises(self.api.BindingError) as caught:
                session.pending_operations()
            self.assertEqual(caught.exception.kind, "reentrancy")
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertTrue(session.close().ok)

    def test_guard_acquisition_interruption_releases_acquired_lock(self):
        class InterruptedLock:
            def __init__(self):
                self.actual = threading.RLock()
            def _is_owned(self):
                return self.actual._is_owned()
            def release(self):
                self.actual.release()
            def acquire(self, blocking=False):
                self.actual.acquire(blocking=blocking)
                raise KeyboardInterrupt("acquire return signal")
        gate = self.impl._Gate()
        gate._lock = InterruptedLock()
        with self.assertRaises(KeyboardInterrupt):
            gate.__enter__()
        self.assertFalse(gate._lock._is_owned())

    def test_open_validation_precedes_native_access(self):
        for path, error in ((None, TypeError), (Path("/bundle"), TypeError),
                            ("", ValueError), ("/bundle\x00bad", ValueError)):
            with self.subTest(path=path), self.assertRaises(error):
                self.api.Session.open(path)
        self.assertEqual(self.native.calls, [])
        with self.assertRaises(TypeError):
            self.api.Session()
        for owner in (self.api.Operation, self.api.ModelOperation):
            with self.assertRaises(TypeError):
                owner()

    def test_missing_extension_and_bundle_errors_keep_actionable_causes(self):
        for error in (ImportError("missing extension"), OSError("incompatible extension")):
            with self.subTest(error=type(error)), mock.patch.object(
                    self.impl.importlib, "import_module", side_effect=error):
                with self.assertRaises(self.api.BindingError) as caught:
                    self.api.build_info()
                self.assertEqual(caught.exception.kind, "bundle")
                self.assertIs(caught.exception.__cause__, error)
                self.assertIn("compatible", str(caught.exception))
        for error in (RuntimeError("unbound wheel"), ValueError("wrong pin"), OSError("missing file")):
            with self.subTest(error=type(error)), mock.patch.object(
                    self.native, "session_open", side_effect=error):
                with self.assertRaises(self.api.BindingError) as caught:
                    self.session()
                self.assertEqual(caught.exception.kind, "bundle")
                self.assertIs(caught.exception.__cause__, error)
                self.assertIn("exact bundle", str(caught.exception))
                self.assertTrue(caught.exception.session.close().ok)

    def test_busy_native_session_maps_to_state_and_retains_empty_owner(self):
        error = BlockingIOError("another SimX context is live")
        with mock.patch.object(self.native, "session_open", side_effect=error):
            with self.assertRaises(self.api.BindingError) as caught:
                self.session()
        self.assertEqual(caught.exception.kind, "state")
        self.assertIs(caught.exception.__cause__, error)
        self.assertEqual(caught.exception.session.pending_operations(), ())
        self.assertTrue(caught.exception.session.close().ok)
        self.assertNotIn("session_close", self.native.calls)

    def test_open_rejects_malformed_result_and_identity_schemas(self):
        for result in (None, [], (None,), (None, status()), (None, {"complete": True})):
            with self.subTest(result=result), mock.patch.object(
                    self.native, "session_open", return_value=result):
                with self.assertRaises(self.api.BindingError) as caught:
                    self.session()
                self.assertEqual(caught.exception.kind, "protocol")
                self.assertIsNotNone(caught.exception.session)
        raw = self.native.session_info(None)
        for value in ({}, dict(raw, format="fp32"), dict(raw, libraries=["one"]),
                      dict(raw, libraries=[None] * 5), dict(raw, source_revision=1)):
            with self.subTest(identity=value), mock.patch.object(
                    self.native, "session_info", return_value=value):
                with self.assertRaises(self.api.BindingError) as caught:
                    self.session()
                self.assertEqual(caught.exception.kind, "protocol")
                self.assertTrue(caught.exception.session.close().ok)

    def test_native_session_creation_failure_and_interrupted_close_retain_session(self):
        handle = {"ops": [], "closed": False}
        with mock.patch.object(self.native, "session_open", return_value=(handle, status(primary=6))):
            with self.assertRaises(self.api.BindingError) as caught:
                self.session()
        session = caught.exception.session
        self.assertEqual(caught.exception.kind, "native")
        self.assertEqual(session.status.primary, 6)
        self.assertTrue(session.close().ok)
        session = self.session()
        error = MemoryError("close publication")
        original = self.native.session_close
        def interrupted(cap):
            original(cap)
            raise error
        with mock.patch.object(self.native, "session_close", side_effect=interrupted):
            with self.assertRaises(MemoryError) as caught:
                session.close()
        self.assertIs(caught.exception.session, session)
        with self.assertRaises(self.api.BindingError):
            session.submit(*self.tensors())
        self.assertTrue(session.close().ok)

    def test_context_timeout_is_bounded_retains_owner_and_chains_body_exception(self):
        session = self.session()
        operation = session.submit(*self.tensors())
        self.native.next_close = status(primary=7, complete=False)
        original = KeyboardInterrupt("body")
        with self.assertRaises(self.api.BindingError) as caught:
            with operation:
                raise original
        self.assertIs(caught.exception.__cause__, original)
        self.assertIs(caught.exception.operation, operation)
        self.assertIs(caught.exception.session, session)
        self.assertEqual(self.native.calls.count(("operation_close", 100_000_000)), 1)
        self.assertEqual(session.pending_operations(), (operation,))
        operation.close()

    def test_successful_context_close_preserves_body_exception_and_rejects_reentry(self):
        session = self.session()
        operation = session.submit(*self.tensors())
        original = ValueError("body")
        with self.assertRaises(ValueError) as caught:
            with operation as entered:
                self.assertIs(entered, operation)
                raise original
        self.assertIs(caught.exception, original)
        self.assertIsNone(caught.exception.__cause__)
        self.assertEqual(session.pending_operations(), ())
        with self.assertRaises(self.api.BindingError) as caught:
            with operation:
                pass
        self.assertEqual(caught.exception.kind, "state")
        with self.assertRaises(ValueError) as caught:
            with session:
                raise original
        self.assertIs(caught.exception, original)

    def test_context_close_exception_retains_original_close_failure(self):
        session = self.session()
        operation = session.submit(*self.tensors())
        error, body = MemoryError("close"), ValueError("body")
        with mock.patch.object(self.native, "operation_close", side_effect=error):
            with self.assertRaises(self.api.BindingError) as caught:
                with operation:
                    raise body
        self.assertEqual(caught.exception.kind, "cleanup")
        self.assertIs(caught.exception.close_error, error)
        self.assertIs(caught.exception.__cause__, body)
        self.assertEqual(session.pending_operations(), (operation,))
        operation.close()

    def test_session_context_cannot_silently_drain_pending_work(self):
        session = self.session()
        operation = session.submit(*self.tensors())
        with self.assertRaises(self.api.BindingError) as caught:
            with session:
                pass
        self.assertIs(caught.exception.session, session)
        self.assertIsNone(caught.exception.operation)
        self.assertEqual(caught.exception.kind, "incomplete")
        self.assertEqual(self.native.calls.count("session_close"), 1)
        self.assertNotIn(("operation_close", 100_000_000), self.native.calls)
        self.assertEqual(session.pending_operations(), (operation,))
        operation.close()
        self.assertTrue(session.close().ok)

    def test_execution_and_model_statuses_are_frozen_and_keep_error_dimensions(self):
        good = self.api.ExecutionStatus(**status())
        self.assertTrue(good.ok)
        self.assertIsNone(good.raise_for_status())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            good.complete = False
        for fields, kind in ((status(validation="bad_shape", primary=6), "validation"),
                             (status(primary=6, cleanup=8, complete=False), "native"),
                             (status(primary=7, complete=False), "incomplete"),
                             (status(primary=7), "native"), (status(cleanup=6), "cleanup"),
                             (status(complete=False), "incomplete")):
            execution = self.api.ExecutionStatus(**fields)
            with self.subTest(fields=fields), self.assertRaises(self.api.BindingError) as caught:
                execution.raise_for_status()
            self.assertEqual(caught.exception.kind, kind)
            self.assertIs(caught.exception.status, execution)
        for name, terminal, kind in (("in_progress", False, "incomplete"),
                                      ("hidden_mismatch", True, "model"),
                                      ("resource_mismatch", True, "model"),
                                      ("closed", True, "model")):
            outcome = self.api.ModelStatus(name, good, terminal)
            with self.subTest(name=name), self.assertRaises(self.api.BindingError) as caught:
                outcome.raise_for_status()
            self.assertEqual(caught.exception.kind, kind)
            self.assertIs(caught.exception.model_status, outcome)
        outcome = self.api.ModelStatus("success", good, True)
        self.assertTrue(outcome.ok)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            outcome.terminal = False

    def test_malformed_native_status_keeps_pending_owner_for_explicit_recovery(self):
        session = self.session()
        invalid = (None, {}, dict(status(), extra=0), status(primary=True),
                   status(cleanup=-1), status(primary=2**32), status(complete=1))
        for raw in invalid:
            with self.subTest(raw=raw), mock.patch.object(self.native, "submit_into", return_value=raw):
                with self.assertRaises(self.api.BindingError) as caught:
                    session.submit(*self.tensors())
                self.assertEqual(caught.exception.kind, "protocol")
                (operation,) = session.pending_operations()
                self.assertIs(caught.exception.operation, operation)
            self.assertTrue(operation.close().ok)
            self.assertEqual(session.pending_operations(), ())

    def test_output_requires_exact_bytes_extent_and_retains_native_failure_cause(self):
        session = self.session()
        operation = session.submit(*self.tensors())
        operation.wait()
        class BytesSubclass(bytes):
            pass
        for raw in (None, bytes(), bytes(124), bytes(132), bytearray(128), BytesSubclass(128)):
            with self.subTest(raw=type(raw)), mock.patch.object(
                    self.native, "operation_output", return_value=raw):
                with self.assertRaises(self.api.BindingError) as caught:
                    operation.output_bytes()
                self.assertEqual(caught.exception.kind, "protocol")
                self.assertIs(caught.exception.operation, operation)
        cause = RuntimeError("output invalid")
        with mock.patch.object(self.native, "operation_output", side_effect=cause):
            with self.assertRaises(self.api.BindingError) as caught:
                operation.output_bytes()
        self.assertEqual(caught.exception.kind, "state")
        self.assertIs(caught.exception.__cause__, cause)
        operation.close()

    def test_diagnostic_json_is_detached_and_requires_an_object(self):
        session = self.session()
        operation = session.submit(*self.tensors())
        trace = operation.trace()
        trace["a"][0] = 99
        self.assertEqual(operation.trace()["a"][0], 0)
        model = session.model(CASES[0])
        record = model.record()
        self.assertEqual(record["trace"]["result"]["status"], "in_progress")
        record["trace"]["result"]["status"] = "changed"
        self.assertEqual(model.record()["trace"]["result"]["status"], "in_progress")
        for native_method, action in (("operation_trace", operation.trace),
                                       ("model_trace", model.trace), ("model_record", model.record)):
            for raw in ({}, "not json", "[]", "null"):
                with self.subTest(method=native_method, raw=raw), mock.patch.object(
                        self.native, native_method, return_value=raw):
                    with self.assertRaises(self.api.BindingError) as caught:
                        action()
                    self.assertEqual(caught.exception.kind, "protocol")
        operation.close()
        model.close()

    def test_model_success_requires_explicit_close_before_native_output_publication(self):
        session = self.session()
        model = session.model(CASES[0])
        self.assertFalse(model.status.ok)
        self.assertFalse(model.advance(0).terminal)
        self.assertTrue(model.advance().ok)
        self.assertEqual(session.pending_operations(), (model,))
        with self.assertRaises(self.api.BindingError) as caught:
            model.output_bytes()
        self.assertEqual(caught.exception.kind, "state")
        self.assertIsInstance(caught.exception.__cause__, RuntimeError)
        self.assertTrue(model.close().ok)
        self.assertTrue(model.status.ok)
        self.assertEqual(model.output_words(), (0,) * 64)
        self.assertEqual(model.record()["iteration"], 0)
        self.assertTrue(model.trace()["owner_closed"])
        self.assertEqual(session.pending_operations(), ())
        calls = tuple(self.native.calls)
        self.assertTrue(model.close().ok)
        self.assertEqual(tuple(self.native.calls), calls)
        self.assertTrue(session.close().ok)

    def test_model_case_and_poison_contract_rejects_before_creation(self):
        session = self.session()
        for case, error in ((None, TypeError), ("caller-model", ValueError), (CASES[5], ValueError)):
            with self.subTest(case=case), self.assertRaises(error):
                session.model(case)
        for poison, error in ((True, TypeError), (-1, ValueError), (2**32, OverflowError)):
            with self.subTest(poison=poison), self.assertRaises(error):
                session.model(CASES[0], poison=poison)
        self.assertNotIn("model_new", self.native.calls)
        self.assertEqual(session.pending_operations(), ())
        for iteration, poison in ((0, 0x7FC0DEAD), (1, 0xDEADBEEF)):
            model = session.model(CASES[0], poison=poison)
            self.assertEqual(model.record(iteration)["iteration"], iteration)
            with self.assertRaises(ValueError):
                model.record(1 - iteration)
            for value, error in ((True, TypeError), (-1, ValueError), (2, ValueError),
                                 (2**32, OverflowError)):
                with self.subTest(iteration=value), self.assertRaises(error):
                    model.record(value)
            model.close()

    def test_model_create_interruptions_and_native_failure_keep_recoverable_owner(self):
        session = self.session()
        for error in (MemoryError("model publication"), KeyboardInterrupt("model signal")):
            self.native.next_create = error
            with self.subTest(error=type(error)), self.assertRaises(type(error)) as caught:
                session.model(CASES[0])
            (model,) = session.pending_operations()
            self.assertIs(caught.exception.operation, model)
            self.assertEqual(model.close().primary, 6)
            self.assertEqual(model.status.status, "runtime_error")
            self.assertEqual(session.pending_operations(), ())
        self.native.next_create = status(primary=6)
        model = session.model(CASES[0])
        self.assertTrue(model.status.terminal)
        self.assertEqual(model.status.status, "runtime_error")
        with self.assertRaises(self.api.BindingError) as caught:
            model.output_bytes()
        self.assertEqual(caught.exception.kind, "native")
        model.close()

    def test_model_close_status_interruption_recovers_without_reclosing_native_owner(self):
        session = self.session()
        for recover_with_advance in (False, True):
            with self.subTest(recover_with_advance=recover_with_advance):
                model = session.model(CASES[0])
                model.advance()
                error = MemoryError("post-close status publication")
                before = self.native.calls.count(("model_close", 100_000_000))
                with mock.patch.object(self.native, "model_advance", side_effect=error):
                    with self.assertRaises(MemoryError) as caught:
                        model.close()
                self.assertIs(caught.exception.operation, model)
                self.assertEqual(session.pending_operations(), (model,))
                for action in (lambda: model.status, model.output_bytes):
                    with self.assertRaises(self.api.BindingError) as caught:
                        action()
                    self.assertEqual(caught.exception.kind, "state")
                if recover_with_advance:
                    self.assertTrue(model.advance(0).ok)
                    self.assertEqual(session.pending_operations(), (model,))
                self.assertTrue(model.close().ok)
                self.assertTrue(model.status.ok)
                self.assertEqual(session.pending_operations(), ())
                self.assertEqual(self.native.calls.count(("model_close", 100_000_000)), before + 1)

    def test_model_early_context_close_is_not_inference_success(self):
        session = self.session()
        with session.model(CASES[0]) as model:
            pass
        self.assertEqual(model.status.status, "closed")
        self.assertTrue(model.status.terminal)
        self.assertFalse(model.status.ok)
        self.assertEqual(session.pending_operations(), ())
        with self.assertRaises(self.api.BindingError) as caught:
            model.output_bytes()
        self.assertEqual(caught.exception.kind, "model")
        self.assertEqual(self.native.calls.count(("model_close", 100_000_000)), 1)
        self.assertEqual(self.native.calls.count(("model_advance", 0)), 1)

    def test_model_terminal_mismatch_is_preserved_by_context_close(self):
        session = self.session()
        model = session.model(CASES[0])
        original = ValueError("body")
        model._handle["model_status"] = model_status("hidden_mismatch", terminal=True)
        with self.assertRaises(self.api.BindingError) as caught:
            with model:
                raise original
        self.assertEqual(caught.exception.kind, "model")
        self.assertIs(caught.exception.__cause__, original)
        self.assertIs(caught.exception.operation, model)
        self.assertIs(caught.exception.session, session)
        self.assertEqual(caught.exception.model_status.status, "hidden_mismatch")
        self.assertEqual(model.status.status, "hidden_mismatch")
        self.assertEqual(session.pending_operations(), ())

    def test_model_malformed_status_and_output_are_protocol_errors(self):
        session = self.session()
        model = session.model(CASES[0])
        for raw in (None, {}, model_status("invented"), model_status(terminal=1),
                    model_status(execution=status(primary=True))):
            with self.subTest(raw=raw), mock.patch.object(
                    self.native, "model_advance", return_value=raw):
                with self.assertRaises(self.api.BindingError) as caught:
                    model.advance()
                self.assertEqual(caught.exception.kind, "protocol")
                self.assertIs(caught.exception.operation, model)
                self.assertEqual(session.pending_operations(), (model,))
        self.assertTrue(model.advance().ok)
        model.close()
        for raw in (bytes(252), bytes(260), bytearray(256)):
            with self.subTest(length=len(raw)), mock.patch.object(
                    self.native, "model_output", return_value=raw):
                with self.assertRaises(self.api.BindingError) as caught:
                    model.output_bytes()
                self.assertEqual(caught.exception.kind, "protocol")

    def test_all_wait_and_close_timeouts_validate_before_native_access(self):
        session = self.session()
        operation = session.submit(*self.tensors())
        model = session.model(CASES[0])
        for action in (operation.wait, operation.close, model.advance, model.close):
            before = tuple(self.native.calls)
            for value, error in ((True, TypeError), (-1, ValueError), (1.0, TypeError),
                                 (1_000_000_001, ValueError), (2**64, OverflowError)):
                with self.subTest(action=action.__name__, value=value), self.assertRaises(error):
                    action(value)
            self.assertEqual(tuple(self.native.calls), before)
        self.assertTrue(operation.wait(1_000_000_000).ok)
        self.assertTrue(model.advance(1_000_000_000).ok)
        self.assertTrue(operation.close(1_000_000_000).ok)
        self.assertTrue(model.close(1_000_000_000).ok)

    def test_memory_info_schema_native_failure_and_closed_state(self):
        session = self.session()
        self.assertEqual(session.memory_info(), (0, 100, 0))
        self.native.memory_result = (6, 0, 0)
        with self.assertRaises(self.api.BindingError) as caught:
            session.memory_info()
        self.assertEqual(caught.exception.kind, "native")
        self.assertEqual(caught.exception.status.primary, 6)
        self.assertIs(caught.exception.session, session)
        for raw in (None, [0, 100, 0], (0, 100), (True, 100, 0), (0, -1, 0), (0, 1.0, 0)):
            self.native.memory_result = raw
            with self.subTest(raw=raw), self.assertRaises(self.api.BindingError) as caught:
                session.memory_info()
            self.assertEqual(caught.exception.kind, "protocol")
        session.close()
        before = tuple(self.native.calls)
        with self.assertRaises(self.api.BindingError) as caught:
            session.memory_info()
        self.assertEqual(caught.exception.kind, "state")
        self.assertEqual(tuple(self.native.calls), before)

    def test_memory_info_rejects_incomplete_session_close_before_native_call(self):
        session = self.session()
        operation = session.submit(*self.tensors())
        self.assertFalse(session.close().complete)
        before = tuple(self.native.calls)
        with self.assertRaises(self.api.BindingError) as caught:
            session.memory_info()
        self.assertEqual(caught.exception.kind, "state")
        self.assertIs(caught.exception.session, session)
        self.assertEqual(tuple(self.native.calls), before)
        self.assertTrue(operation.close().complete)
        self.assertTrue(session.close().ok)


if __name__ == "__main__":
    unittest.main()
