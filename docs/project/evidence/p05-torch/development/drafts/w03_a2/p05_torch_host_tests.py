#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Real PyTorch registration/ownership tests with scripted HOST-ONLY native responses."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import struct
import sys
import threading
import time
import traceback
import unittest
from unittest import mock


SCOPE = "host-only-real-pytorch-scripted-native-mock"
SHAPES = ((8, 4, 8), (8, 4, 16), (16, 8, 16))
FORMATS = ("fp16", "bf16")
POISONS = (0x7FC0DEAD, 0xDEADBEEF)
EDGE32 = (0, 0x80000000, 1, 0x007FFFFF, 0x00800000, 0x3F800000,
          0x7F7FFFFF, 0x7F800000, 0xFF800000, 0x7FC01234, 0x7F801234,
          0xFFC01234, 0xFF801234, *POISONS)


def words16(values):
    return struct.pack("<" + "H" * len(values), *values)


def words32(values):
    return struct.pack("<" + "I" * len(values), *values)


def tensor_bytes(value):
    values = value.view(torch.int32).flatten().tolist()
    return struct.pack("<" + "i" * len(values), *values)


def tensor16(raw, dtype, shape, *, column=False):
    result = torch.frombuffer(bytearray(raw), dtype=dtype).clone()
    return result.reshape(shape[1], shape[0]).t() if column else result.reshape(shape)


def observed_native():
    class ObservedNative(NativeMock):
        def __init__(self):
            super().__init__()
            self.submitted = []
            self.models = []

        def submit_into(self, session, operation, m, n, k, a, b, poison):
            result = super().submit_into(session, operation, m, n, k, a, b, poison)
            operation["output"] = words32([EDGE32[i % len(EDGE32)] for i in range(m * n)])
            self.submitted.append(operation)
            return result

        def operation_output(self, operation):
            if not operation["closed"]:
                raise AssertionError("framework published matmul output before explicit close")
            return super().operation_output(operation)

        def model_create_into(self, session, operation, case, poison):
            result = super().model_create_into(session, operation, case, poison)
            self.models.append(operation)
            return result

        def model_output(self, operation):
            super().model_output(operation)
            return words32([EDGE32[i % len(EDGE32)] for i in range(64)])

    return ObservedNative()


class HostTorchTests(unittest.TestCase):
    def setUp(self):
        self.native = observed_native()
        self.saved_native = sys.modules.get("vortex_ai._native")
        sys.modules["vortex_ai._native"] = self.native
        self.owners = []
        self.session, self.adapter = self.open("fp16")

    def tearDown(self):
        for session, adapter in reversed(self.owners):
            for operation in session.pending_operations():
                operation.close()
            adapter.close()
            session.close()
        if self.saved_native is None:
            sys.modules.pop("vortex_ai._native", None)
        else:
            sys.modules["vortex_ai._native"] = self.saved_native

    def open(self, dtype):
        self.native.format = dtype
        session = api.Session.open("/host-only/scripted-bundle")
        adapter = ops.TorchSession(session)
        self.owners.append((session, adapter))
        return session, adapter

    def close_current(self):
        self.adapter.close()
        self.assertTrue(self.session.close().ok)

    def select_format(self, dtype):
        if self.session.info["format"] != dtype:
            self.close_current()
            self.session, self.adapter = self.open(dtype)

    def tensors(self, shape=(8, 4, 8), *, dtype=None, start=0):
        m, n, k = shape
        dtype = dtype or self.session.info["format"]
        torch_dtype = torch.float16 if dtype == "fp16" else torch.bfloat16
        raw_a = words16([(start + i * 997) & 0xFFFF for i in range(m * k)])
        raw_b = words16([(start + 313 + i * 1543) & 0xFFFF for i in range(k * n)])
        return (tensor16(raw_a, torch_dtype, (m, k)),
                tensor16(raw_b, torch_dtype, (k, n), column=True), raw_a, raw_b)

    def counts(self):
        return sum(isinstance(call, tuple) and call[0] in ("submit", "model_create")
                   for call in self.native.calls)

    def raw(self, a, b, *, token=None, poison=POISONS[0]):
        return torch.ops.vortex_ai.matmul_v1(
            a, b, self.adapter.token if token is None else token, poison)

    def raw_model(self, *, token=None, case=None, poison=POISONS[0]):
        return torch.ops.vortex_ai.fixed_mlp_v1(
            self.session.info["format"] + "-seeded_dense" if case is None else case,
            self.adapter.token if token is None else token, poison)

    def rejected_before_submit(self, call):
        before = self.counts()
        with self.assertRaises((ValueError, TypeError, RuntimeError)):
            call()
        self.assertEqual(self.counts(), before, "rejected call reached scripted native execution")
        self.assertFalse(self.session.pending_operations())

    def assert_output(self, result, operation, shape):
        self.assertIs(type(result), torch.Tensor)
        self.assertEqual(tuple(result.shape), shape)
        self.assertEqual(result.dtype, torch.float32)
        self.assertEqual(result.device.type, "cpu")
        self.assertEqual(result.stride(), (shape[1], 1))
        self.assertEqual(result.storage_offset(), 0)
        self.assertFalse(result.requires_grad)
        self.assertEqual(tensor_bytes(result), operation.output_bytes())
        self.assertTrue(operation.close().ok)
        self.assertFalse(self.session.pending_operations())

    def check_signature(self, dtype, shape):
        self.select_format(dtype)
        a, b, raw_a, raw_b = self.tensors(shape)
        for poison in POISONS:
            result = self.raw(a, b, poison=poison)
            operation = self.adapter.last_operation
            self.assertEqual(self.native.submitted[-1]["a"], raw_a)
            self.assertEqual(self.native.submitted[-1]["b"], raw_b)
            self.assert_output(result, operation, (shape[0], shape[1]))
            self.assertEqual(next(call for call in reversed(self.native.calls)
                                  if isinstance(call, tuple) and call[0] == "submit")[-1], poison)

    def check_all_encodings(self, dtype):
        self.select_format(dtype)
        torch_dtype = torch.float16 if dtype == "fp16" else torch.bfloat16
        for start in range(0, 65536, 128):
            raw_a = words16([(start + i) & 0xFFFF for i in range(256)])
            raw_b = words16([start + i for i in range(128)])
            a = tensor16(raw_a, torch_dtype, (16, 16))
            b = tensor16(raw_b, torch_dtype, (16, 8), column=True)
            self.raw(a, b)
            self.assertEqual(self.native.submitted[-1]["a"], raw_a)
            self.assertEqual(self.native.submitted[-1]["b"], raw_b)
        self.assertFalse(self.session.pending_operations())

    def test_all_fixed_cases_are_fresh_owned_fp32_outputs(self):
        for dtype in FORMATS:
            self.select_format(dtype)
            for case in api.fixture_cases():
                if not case.startswith(dtype + "-"):
                    continue
                for poison in POISONS:
                    result = self.raw_model(case=case, poison=poison)
                    operation = self.adapter.last_operation
                    self.assertIs(type(operation), api.ModelOperation)
                    self.assertTrue(operation.status.ok)
                    self.assert_output(result, operation, (16, 4))
                    self.assertEqual(self.native.models[-1]["case"], case)
                    self.assertEqual(self.native.models[-1]["poison"], poison)

    def test_input_copy_and_output_independence(self):
        a, b, raw_a, raw_b = self.tensors()
        self.native.on_submit = lambda: (a.zero_(), b.zero_())
        result = self.adapter.matmul(a, b)
        operation = self.adapter.last_operation
        self.assertEqual(self.native.submitted[-1]["a"], raw_a)
        self.assertEqual(self.native.submitted[-1]["b"], raw_b)
        original = operation.output_bytes()
        result.zero_()
        self.assertEqual(operation.output_bytes(), original)
        fresh = self.adapter.matmul(*self.tensors()[:2])
        expected = tensor_bytes(fresh)
        self.native.submitted[-1]["output"] = bytes(len(expected))
        self.close_current()
        self.assertEqual(tensor_bytes(fresh), expected)

    def test_ordinary_no_grad_and_inference_mode(self):
        a, b, *_ = self.tensors()
        with torch.no_grad():
            self.assert_output(self.raw(a, b), self.adapter.last_operation, (8, 4))
        with torch.inference_mode():
            self.assert_output(self.raw(a, b), self.adapter.last_operation, (8, 4))

    def test_requires_grad_rejected_even_under_no_grad(self):
        a, b, *_ = self.tensors()
        for operand in (a, b):
            operand.requires_grad_(True)
            self.rejected_before_submit(lambda: self.raw(a, b))
            with torch.no_grad():
                self.rejected_before_submit(lambda: self.raw(a, b))
            operand.requires_grad_(False)

    def test_forward_ad_dual_rejected_before_integer_view(self):
        a, b, *_ = self.tensors()
        with torch.autograd.forward_ad.dual_level():
            dual = torch.autograd.forward_ad.make_dual(a, torch.ones_like(a))
            self.assertFalse(dual.requires_grad)
            self.rejected_before_submit(lambda: self.raw(dual, b))

    def test_autocast_rejected_for_both_operators(self):
        a, b, *_ = self.tensors()
        with torch.autocast("cpu"):
            self.rejected_before_submit(lambda: self.raw(a, b))
            self.rejected_before_submit(self.raw_model)

    def test_meta_fake_and_subclass_rejected(self):
        a, b, *_ = self.tensors()
        self.rejected_before_submit(lambda: self.raw(a.to("meta"), b.to("meta")))
        class Subclass(torch.Tensor):
            pass
        self.rejected_before_submit(lambda: self.raw(a.as_subclass(Subclass), b))
        from torch._subclasses.fake_tensor import FakeTensorMode
        with FakeTensorMode() as mode:
            fake_a, fake_b = mode.from_tensor(a), mode.from_tensor(b)
            self.rejected_before_submit(lambda: self.raw(fake_a, fake_b))
            self.rejected_before_submit(self.raw_model)

    def test_negative_lazy_view_rejected_in_both_dispatch_modes(self):
        a, b, *_ = self.tensors()
        self.rejected_before_submit(lambda: self.raw(torch._neg_view(a), b))
        with torch.inference_mode():
            self.rejected_before_submit(lambda: self.raw(torch._neg_view(a), b))

    def test_invalid_tensor_representations_rejected(self):
        a, b, *_ = self.tensors()
        invalid = (
            (a.to(torch.float32), b), (a, b.to(torch.bfloat16)),
            (a.unsqueeze(0), b), (a.t(), b), (a, b.contiguous()),
            (torch.empty((8, 9), dtype=a.dtype)[:, :8], b),
            (torch.empty(65, dtype=a.dtype)[1:].view(8, 8), b),
            (torch.empty(1, 8, dtype=a.dtype).expand(8, 8), b),
            (torch.empty(8, 8, dtype=a.dtype).as_strided((8, 8), (1, 1)), b),
            (torch.empty(8, 8, dtype=a.dtype).to_sparse(), b),
            (torch.empty(4, 8, dtype=a.dtype), b),
            (torch.empty(0, 8, dtype=a.dtype), b),
            (torch.empty(8, 8, dtype=torch.complex64).conj(), b),
            (torch.empty(128, dtype=a.dtype)[:64].view(8, 8), b),
        )
        for index, (left, right) in enumerate(invalid):
            with self.subTest(representation=index):
                self.rejected_before_submit(lambda: self.raw(left, right))

    def test_unknown_stale_tokens_and_invalid_cases_rejected(self):
        a, b, *_ = self.tensors()
        for token in (-1, 0, (1 << 63) - 1):
            self.rejected_before_submit(lambda token=token: self.raw(a, b, token=token))
            self.rejected_before_submit(lambda token=token: self.raw_model(token=token))
        for case in ("", "fp16-unknown", "bf16-seeded_dense"):
            self.rejected_before_submit(lambda case=case: self.raw_model(case=case))
        token = self.adapter.token
        self.adapter.close()
        self.rejected_before_submit(lambda: self.raw(a, b, token=token))
        self.rejected_before_submit(lambda: self.raw_model(token=token))

    def test_invalid_poison_rejected_before_submission(self):
        a, b, *_ = self.tensors()
        for poison in (-1, 1 << 32):
            self.rejected_before_submit(lambda poison=poison: self.raw(a, b, poison=poison))
            self.rejected_before_submit(lambda poison=poison: self.raw_model(poison=poison))

    def test_adapter_borrows_session_and_detaches_without_closing_it(self):
        self.assertIs(self.adapter.session, self.session)
        original_token = self.adapter.token
        self.adapter.close()
        self.assertNotIn("session_close", self.native.calls)
        self.assertTrue(self.session.memory_info()[0] == 0)
        replacement = ops.TorchSession(self.session)
        self.owners.append((self.session, replacement))
        self.assertNotEqual(replacement.token, original_token)
        self.assertEqual(tuple(replacement.matmul(*self.tensors()[:2]).shape), (8, 4))

    def test_failed_session_initialization_rejected_before_attach(self):
        self.close_current()
        failures = (
            ("native_status", "session_open", {"return_value": (
                {"ops": [], "closed": False}, native_status(primary=6))}),
            ("identity_schema", "session_info", {"return_value": {"format": "fp16"}}),
            ("identity_interruption", "session_info", {
                "side_effect": KeyboardInterrupt("injected identity interruption")}),
            ("status_schema", "session_open", {"return_value": (
                {"ops": [], "closed": False}, {"primary": 6})}),
        )
        for name, method, fault in failures:
            with self.subTest(failure=name):
                with mock.patch.object(self.native, method, **fault):
                    try:
                        api.Session.open("/host-only/scripted-bundle")
                    except BaseException as error:
                        failed_session = error.session
                    else:
                        self.fail("scripted opening fault did not raise")
                attempted_adapter = None
                try:
                    with self.assertRaises(api.BindingError) as caught:
                        attempted_adapter = ops.TorchSession(failed_session)
                    self.assertIs(caught.exception.session, failed_session)
                    self.assertEqual(dict(failed_session.info), {})
                    self.assertFalse(failed_session.pending_operations())
                finally:
                    if attempted_adapter is not None:
                        attempted_adapter.close()
                    self.assertTrue(failed_session.close().ok)
        self.assertEqual(self.counts(), 0)

    def test_duplicate_attach_error_retains_existing_adapter(self):
        with self.assertRaises(api.BindingError) as caught:
            ops.TorchSession(self.session)
        self.assertIs(caught.exception.adapter, self.adapter)
        self.assertIs(caught.exception.session, self.session)
        self.assertIs(caught.exception.adapter.session, self.session)
        self.assertEqual(self.counts(), 0)

    def test_constructor_return_interruption_keeps_recoverable_adapter(self):
        self.adapter.close()
        previous_trace = sys.gettrace()
        def interrupt_return(frame, event, _arg):
            if frame.f_code is ops.TorchSession.__init__.__code__ and event == "return":
                raise KeyboardInterrupt("injected constructor return interruption")
            return interrupt_return
        try:
            sys.settrace(interrupt_return)
            with self.assertRaises(KeyboardInterrupt):
                ops.TorchSession(self.session)
        finally:
            sys.settrace(previous_trace)
        with self.assertRaises(api.BindingError) as caught:
            ops.TorchSession(self.session)
        recovered = caught.exception.adapter
        self.owners.append((self.session, recovered))
        self.assertIs(recovered.session, self.session)
        self.assertNotEqual(recovered.token, 0)
        self.assertFalse(recovered.pending_operations())
        recovered.close()
        replacement = ops.TorchSession(self.session)
        self.owners.append((self.session, replacement))
        self.assertNotEqual(replacement.token, recovered.token)
        output = replacement.matmul(*self.tensors()[:2])
        self.assert_output(output, replacement.last_operation, (8, 4))

    def test_repeated_matmul_model_matmul_closes_every_owner(self):
        for _ in range(3):
            self.adapter.matmul(*self.tensors()[:2])
            first = self.adapter.last_operation
            self.assertFalse(self.session.pending_operations())
            self.adapter.fixed_mlp("fp16-seeded_dense")
            model = self.adapter.last_operation
            self.assertIsNot(first, model)
            self.assertTrue(model.status.ok)
            self.assertFalse(self.session.pending_operations())
            self.adapter.matmul(*self.tensors()[:2])
            self.assertIsNot(self.adapter.last_operation, first)
            self.assertFalse(self.session.pending_operations())

    def test_partial_submission_error_retains_owner_and_blocks_resubmission(self):
        self.native.next_submit = native_status(primary=6, complete=False)
        with self.assertRaises(api.BindingError):
            self.adapter.matmul(*self.tensors()[:2])
        pending = self.session.pending_operations()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].status.primary, 6)
        before = self.counts()
        with self.assertRaises(api.BindingError):
            self.adapter.matmul(*self.tensors()[:2])
        self.assertEqual(self.counts(), before)
        with self.assertRaises(api.BindingError):
            self.adapter.close()
        self.assertTrue(pending[0].close().complete)
        self.assertEqual(tuple(self.adapter.matmul(*self.tensors()[:2]).shape), (8, 4))

    def test_keyboard_interrupt_during_submit_retains_session_owner(self):
        self.native.next_submit = KeyboardInterrupt("injected submission interruption")
        with self.assertRaises(KeyboardInterrupt):
            self.adapter.matmul(*self.tensors()[:2])
        self.assertEqual(len(self.session.pending_operations()), 1)
        self.assertNotIn("operation_output", self.native.calls)

    def test_memory_error_during_submit_retains_session_owner(self):
        self.native.next_submit = MemoryError("injected submission allocation failure")
        with self.assertRaises(MemoryError):
            self.adapter.matmul(*self.tensors()[:2])
        self.assertEqual(len(self.session.pending_operations()), 1)

    def test_wait_deadline_retains_operation_for_explicit_recovery(self):
        self.adapter.close()
        self.adapter = ops.TorchSession(self.session, timeout_seconds=0.001)
        self.owners.append((self.session, self.adapter))
        original = self.native.operation_wait
        def timed_out(cap, timeout):
            time.sleep(0.003)
            return native_status(primary=7, complete=False)
        with mock.patch.object(self.native, "operation_wait", side_effect=timed_out):
            with self.assertRaises((api.BindingError, TimeoutError)):
                self.adapter.matmul(*self.tensors()[:2])
        pending = self.session.pending_operations()
        self.assertEqual(len(pending), 1)
        self.assertNotIn("operation_output", self.native.calls)
        self.assertTrue(pending[0].wait().ok)
        self.assertTrue(pending[0].close().ok)
        self.assertFalse(self.session.pending_operations())
        self.assertIs(self.native.operation_wait.__func__, original.__func__)

    def test_cleanup_error_never_publishes_output(self):
        self.native.next_close = native_status(cleanup=6)
        with self.assertRaises(api.BindingError) as caught:
            self.adapter.matmul(*self.tensors()[:2])
        self.assertEqual(caught.exception.status.cleanup, 6)
        self.assertNotIn("operation_output", self.native.calls)
        self.assertFalse(self.session.pending_operations())

    def test_model_failure_never_publishes_output(self):
        self.native.next_create = native_status(primary=6)
        with self.assertRaises(api.BindingError):
            self.adapter.fixed_mlp("fp16-seeded_dense")
        self.assertEqual(len(self.session.pending_operations()), 1)
        self.assertNotIn("model_output", self.native.calls)

    def test_model_numerical_mismatch_is_not_cleanup_success(self):
        def mismatch(cap, timeout):
            cap["model_status"] = native_model_status("hidden_mismatch", terminal=True)
            return cap["model_status"]
        with mock.patch.object(self.native, "model_advance", side_effect=mismatch):
            with self.assertRaises(api.BindingError):
                self.adapter.fixed_mlp("fp16-seeded_dense")
        self.assertNotIn("model_output", self.native.calls)

    def test_output_allocation_failure_occurs_after_native_close(self):
        a, b, *_ = self.tensors()
        with mock.patch.object(torch, "frombuffer", side_effect=MemoryError("injected output failure")):
            with self.assertRaises(MemoryError):
                self.raw(a, b)
        self.assertFalse(self.session.pending_operations())
        self.assertTrue(self.native.submitted[-1]["closed"])
        self.assertEqual(tuple(self.raw(a, b).shape), (8, 4))

    def test_reentrant_submission_is_rejected_before_second_native_call(self):
        a, b, *_ = self.tensors()
        caught = []
        def reenter():
            try:
                self.raw(a, b)
            except api.BindingError as error:
                caught.append(error)
        self.native.on_submit = reenter
        self.raw(a, b)
        self.assertEqual(len(caught), 1)
        self.assertEqual(self.counts(), 1)

    def test_concurrent_submission_rejected_while_first_is_owned(self):
        a, b, *_ = self.tensors()
        entered, release = threading.Event(), threading.Event()
        errors = []
        def hold():
            entered.set()
            if not release.wait(5):
                raise RuntimeError("host test synchronization timed out")
        self.native.on_submit = hold
        def work():
            try:
                self.raw(a, b)
            except BaseException as error:
                errors.append(error)
        worker = threading.Thread(target=work)
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            with self.assertRaises(api.BindingError):
                self.raw(a, b)
        finally:
            release.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self.counts(), 1)

    def test_cross_process_identity_rejected_without_native_entry(self):
        a, b, *_ = self.tensors()
        parent_pid = os.getpid()
        before = self.counts()
        with mock.patch.object(os, "getpid", return_value=parent_pid + 1):
            with self.assertRaises(api.BindingError):
                self.raw(a, b)
        self.assertEqual(self.counts(), before)
        self.assertFalse(self.session.pending_operations())

    def test_vmap_rejected_for_matmul_and_input_free_model(self):
        a, b, *_ = self.tensors()
        self.rejected_before_submit(lambda: torch.vmap(lambda x: self.raw(x, b))(a.unsqueeze(0)))
        self.rejected_before_submit(lambda: torch.vmap(lambda x: self.raw_model())(a.unsqueeze(0)))

    def test_functionalize_rejected_for_both_operators(self):
        a, b, *_ = self.tensors()
        self.rejected_before_submit(lambda: torch.func.functionalize(lambda x: self.raw(x, b))(a))
        self.rejected_before_submit(lambda: torch.func.functionalize(
            lambda x: self.raw_model() + x)(torch.zeros(16, 4)))

    def test_jvp_rejected_for_both_operators(self):
        a, b, *_ = self.tensors()
        self.rejected_before_submit(lambda: torch.func.jvp(
            lambda x: self.raw(x, b), (a,), (torch.ones_like(a),)))
        self.rejected_before_submit(lambda: torch.func.jvp(
            lambda x: self.raw_model() + x, (torch.zeros(16, 4),), (torch.ones(16, 4),)))

    def test_compile_rejected_for_both_operators(self):
        a, b, *_ = self.tensors()
        self.rejected_before_submit(lambda: torch.compile(
            lambda x, y: self.raw(x, y), backend="eager", fullgraph=True)(a, b))
        self.rejected_before_submit(lambda: torch.compile(
            lambda x: self.raw_model() + x, backend="eager", fullgraph=True)(torch.zeros(16, 4)))

    def test_torchscript_trace_rejected_for_both_operators(self):
        a, b, *_ = self.tensors()
        self.rejected_before_submit(lambda: torch.jit.trace(lambda x: self.raw(x, b), a))
        self.rejected_before_submit(lambda: torch.jit.trace(
            lambda x: self.raw_model() + x, torch.zeros(16, 4)))


for _dtype in FORMATS:
    for _shape in SHAPES:
        def signature(self, dtype=_dtype, shape=_shape):
            self.check_signature(dtype, shape)
        setattr(HostTorchTests, "test_signature_" + _dtype + "_" + "x".join(map(str, _shape)), signature)
    def all_encodings(self, dtype=_dtype):
        self.check_all_encodings(dtype)
    setattr(HostTorchTests, "test_all_16bit_encodings_" + _dtype, all_encodings)


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.observations = []
        self.started = {}

    def startTest(self, test):
        self.started[id(test)] = time.monotonic()
        super().startTest(test)

    def _record(self, test, outcome, detail=None):
        row = {"test": test.id(), "outcome": outcome,
               "duration_seconds": time.monotonic() - self.started.get(id(test), time.monotonic())}
        if detail is not None:
            row["detail"] = detail
        self.observations.append(row)

    def addSuccess(self, test):
        self._record(test, "pass")
        super().addSuccess(test)

    def addFailure(self, test, error):
        self._record(test, "fail", self._exc_info_to_string(error, test))
        super().addFailure(test, error)

    def addError(self, test, error):
        self._record(test, "error", self._exc_info_to_string(error, test))
        super().addError(test, error)

    def addSkip(self, test, reason):
        self._record(test, "skip", reason)
        super().addSkip(test, reason)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--adapter", type=Path, help="explicit development draft; never installed qualification")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--case", action="append", default=[])
    args = parser.parse_args(argv)
    source = args.source_dir.resolve(strict=True)
    report = {"schema_version": 1, "scope": SCOPE, "acceptance_claimed": False,
              "native_execution": "not_run", "python_version": platform.python_version(),
              "outcome": "blocked", "source_files": [], "tests": []}
    result = None
    try:
        global torch, api, ops, NativeMock, native_status, native_model_status
        import torch
        if torch.__version__ != "2.15.0+cpu":
            raise RuntimeError("host contract tests require torch==2.15.0+cpu")
        report["torch_version"] = torch.__version__
        sys.path.insert(0, str(source / "ci/project"))
        sys.path.insert(0, str(source / "python"))
        from test_p05_python_api import NativeMock, status as native_status, model_status as native_model_status
        import vortex_ai as api
        if args.adapter:
            adapter_path = args.adapter.resolve(strict=True)
            spec = importlib.util.spec_from_file_location("vortex_ai.torch_ops", adapter_path)
            ops = importlib.util.module_from_spec(spec)
            sys.modules["vortex_ai.torch_ops"] = ops
            spec.loader.exec_module(ops)
        else:
            from vortex_ai import torch_ops as ops
            adapter_path = Path(ops.__file__).resolve(strict=True)
        paths = [Path(__file__).resolve(), adapter_path, source / "python/vortex_ai/_api.py",
                 source / "ci/project/test_p05_python_api.py"]
        report["source_files"] = [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                                  for path in paths]
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(HostTorchTests)
        if args.case:
            selected = [case for case in suite if any(case.id().endswith(name) for name in args.case)]
            if len(selected) != len(args.case):
                raise ValueError("each --case must select exactly one distinct test")
            suite = unittest.TestSuite(selected)
        result = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(suite)
        report.update(tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                      skips=len(result.skipped), tests=result.observations,
                      outcome="pass" if result.wasSuccessful() and not result.skipped and result.testsRun else "fail")
    except BaseException as error:
        report.update(outcome="fail", error=type(error).__name__ + ": " + str(error),
                      traceback=traceback.format_exc())
        traceback.print_exc()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print("P05_TORCH_HOST " + json.dumps({key: report.get(key) for key in
          ("scope", "outcome", "torch_version", "tests_run", "failures", "errors", "skips")}, sort_keys=True))
    return 0 if report["outcome"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
