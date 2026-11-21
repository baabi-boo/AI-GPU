# SPDX-License-Identifier: Apache-2.0
"""Compiled CPython boundary checks with a HOST-ONLY fault-injection runtime.

These fake DSOs execute no accelerator arithmetic or SimX backend. Generic
outputs are synthetic words; model outputs are frozen responses gated on the
actual transferred inputs. Passing tests establish no numerical qualification.
Publication faults mock Python status conversion only after the unchanged
compiled native call returns; they do not replace the native operation or use
a global CPython allocator hook.

Run from the source root with:
    python3 -m unittest discover -s ci/project -p test_p05_native_binding.py -v

Both format extensions are built sequentially once for this suite. Every case
runs in a fresh child: native cleanup poison deliberately cannot be reset.
Set P05_NATIVE_TEST_WORKDIR to a new/empty directory to retain build commands,
source identities, the test snapshot, child launchers, and results.json.
"""

from __future__ import annotations

import gc
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import sysconfig
import tempfile
import time
import unittest
from unittest import mock
import weakref

from p05_test_runtime import ROOT, SCOPE, FaultControls, build_test_runtime


FORMATS = ("fp16", "bf16")
SHAPES = ((8, 4, 8), (8, 4, 16), (16, 8, 16))
MODEL_NAMES = ("seeded_dense", "negated_dense", "zero", "signed_basis", "split_boundary")
SCENARIOS = {}


def register(name, function, *arguments, dtype="fp16"):
    key = f"{dtype}_{name}"
    if key in SCENARIOS:
        raise ValueError(f"duplicate native scenario: {key}")
    SCENARIOS[key] = (dtype, function, arguments)


class ChildChecks:
    def __init__(self, dtype):
        from vortex_ai import BindingError, Session, Tensor, _native
        self.Session, self.Tensor, self.BindingError = Session, Tensor, BindingError
        self.native = _native
        self.bundle = os.environ["P05_TEST_BUNDLE"]
        self.dtype = dtype
        self.case = f"{dtype}-seeded_dense"
        self.controls = FaultControls.activate(self.bundle)
        self.metrics = {}

    def open(self):
        return self.Session.open(self.bundle)

    def tensors(self, m=8, n=4, k=8):
        a = self.Tensor(bytearray([0x12] * (m * k * 2)), dtype=self.dtype,
                        shape=(m, k), layout="row_major")
        b = self.Tensor(bytearray([0x34] * (k * n * 2)), dtype=self.dtype,
                        shape=(k, n), layout="column_major")
        return a, b

    def submit(self, session, m=8, n=4, k=8):
        return session.submit(*self.tensors(m, n, k))

    def model(self, session, case=None):
        case = self.case if case is None else case
        self.controls.select_case(case)
        return session.model(case)

    def blocked_open(self, *, poison=False):
        before = self.controls.counter("calls:device_open")
        try:
            session = self.open()
        except self.BindingError as error:
            assert error.kind == "state", error.kind
            if poison:
                assert "cleanup failed" in str(error), str(error)
        else:
            session.close()
            raise AssertionError("overlapping or poisoned native context was accepted")
        assert self.controls.counter("calls:device_open") == before

    def blocked_work(self, call):
        before = self.controls.counter("calls:device_open")
        try:
            value = call()
        except self.BindingError as error:
            assert error.kind == "state", error.kind
            retained = getattr(error, "operation", None)
            if retained is not None:
                assert retained.close(0).complete
        else:
            if hasattr(value, "close"):
                value.close(0)
            raise AssertionError("conflicting native work was accepted")
        assert self.controls.counter("calls:device_open") == before

    def no_output(self, operation):
        try:
            operation.output_bytes()
        except self.BindingError:
            pass
        else:
            raise AssertionError("output was published for incomplete or failed work")

    def reopen(self):
        session = self.open()
        assert session.close().ok

    def done(self):
        self.controls.assert_no_resources()
        assert self.controls.counter("max_live_devices") <= 1, self.controls.counters
        assert self.controls.counter("input_copy_mismatches") == 0


def overlap(h):
    session = h.open()
    h.blocked_open()
    assert h.controls.counter("devices") == 1
    first = h.submit(session)
    before = h.controls.counter("calls:queue_create")
    h.blocked_work(lambda: h.submit(session))
    assert first.wait(0).ok
    h.blocked_work(lambda: h.submit(session))
    assert h.controls.counter("calls:queue_create") == before
    assert session.pending_operations() == (first,)
    assert first.close(0).ok
    second = h.submit(session)
    assert second.close(0).ok
    assert h.controls.counter("calls:queue_create") == before + 1
    assert session.close().ok
    h.reopen()


def native_second_submission(h):
    session, _ = h.native.session_open(h.bundle)
    first, second = h.native.operation_new(), h.native.operation_new()
    arguments = (8, 4, 8, bytes(128), bytes(64), 0x7FC0DEAD)
    h.native.submit_into(session, first, *arguments)
    before = h.controls.counter("calls:queue_create")
    for waited in (False, True):
        if waited:
            assert h.native.operation_wait(first, 0)["complete"]
        try:
            h.native.submit_into(session, second, *arguments)
        except BlockingIOError:
            pass
        else:
            raise AssertionError("a second native queue was accepted before explicit close")
        assert h.controls.counter("calls:queue_create") == before
    assert h.native.operation_close(first, 0)["complete"]
    h.native.submit_into(session, second, *arguments)
    assert h.controls.counter("calls:queue_create") == before + 1
    assert h.native.operation_close(second, 0)["complete"]
    assert h.native.session_close(session)["complete"]


def rejected_empty_owner_state(h):
    session = h.open()
    active = h.submit(session)
    for create, kind in ((lambda: h.submit(session), "operation"),
                         (lambda: h.model(session), "model")):
        try:
            create()
        except h.BindingError as error:
            assert error.kind == "state" and error.session is session
            empty = error.operation
        else:
            raise AssertionError("conflicting native creation succeeded")
        calls = (lambda: empty.wait(0), empty.trace) if kind == "operation" else (
            lambda: empty.advance(0), empty.trace, empty.record)
        for call in calls:
            try:
                call()
            except h.BindingError as error:
                assert error.kind == "state" and error.operation is empty
                assert error.session is session
            else:
                raise AssertionError("empty owner progress or diagnostics succeeded")
        assert empty.close(0).complete
        assert session.pending_operations() == (active,)
    assert active.close(0).ok
    assert session.close().ok
    h.reopen()


def pending_after_wait(h):
    session = h.open()
    operation = h.submit(session)
    reference = weakref.ref(operation)
    assert session.pending_operations() == (operation,)
    assert operation.wait(0).ok
    saved = operation.output_bytes()
    del operation
    gc.collect()
    assert reference() is session.pending_operations()[0]
    status = session.close()
    assert not status.complete and status.primary == 7
    try:
        session.memory_info()
    except h.BindingError as error:
        assert error.kind == "state" and error.session is session
    else:
        raise AssertionError("closing session exposed memory information")
    h.blocked_open()
    operation = session.pending_operations()[0]
    assert operation.close(0).ok
    assert session.pending_operations() == ()
    assert session.close().ok
    assert operation.output_bytes() == saved
    h.reopen()


def orphaned_operation(h):
    session = h.open()
    operation = h.submit(session)
    reference = weakref.ref(session)
    del session
    gc.collect()
    assert reference() is None
    h.blocked_open()
    h.controls.timeout(1)
    assert not operation.close(0).complete
    h.blocked_open()
    assert operation.wait(0).ok
    saved = operation.output_bytes()
    h.blocked_open()
    assert operation.close(0).ok
    assert operation.output_bytes() == saved
    h.reopen()


def model_handoff(h):
    session = h.open()
    model = h.model(session)
    assert h.controls.counter("devices") == 1
    assert h.controls.counter("calls:device_open") == 2
    h.blocked_open()
    h.blocked_work(lambda: h.submit(session))
    h.blocked_work(lambda: session.model(h.case))
    h.blocked_work(session.memory_info)
    assert model.advance(0).ok
    h.blocked_open()
    assert model.close(0).ok
    saved = model.output_bytes()
    operation = h.submit(session)
    assert h.controls.counter("calls:device_open") == 3
    assert operation.close(0).ok
    assert model.output_bytes() == saved
    assert session.close().ok


def suspended_session_close(h):
    session = h.open()
    model = h.model(session)
    assert session.close().ok
    h.blocked_open()
    assert model.advance(0).ok
    assert model.close(0).ok
    assert len(model.output_bytes()) == 256
    h.reopen()


def waited_operation_blocks_handoff(h):
    session = h.open()
    operation = h.submit(session)
    assert operation.wait(0).ok
    h.blocked_work(lambda: session.model(h.case))
    assert h.controls.counter("devices") == 1
    assert operation.close(0).ok
    model = h.model(session)
    assert model.close(0).complete
    assert session.close().ok


def suspended_session_competes(h):
    suspended = h.open()
    model = h.model(suspended)
    assert model.close(0).ok
    current = h.open()
    h.blocked_work(lambda: h.submit(suspended))
    h.blocked_work(suspended.memory_info)
    assert current.close().ok
    operation = h.submit(suspended)
    assert operation.close(0).ok
    assert suspended.close().ok


def incomplete_model_close(h):
    session = h.open()
    model = h.model(session)
    h.controls.timeout(3)
    assert not model.advance(0).execution.complete
    assert not model.close(0).complete
    assert session.pending_operations() == (model,)
    h.blocked_open()
    h.blocked_work(lambda: h.submit(session))
    assert not model.close(0).complete
    assert model.close(0).complete
    assert session.pending_operations() == ()
    operation = h.submit(session)
    assert operation.close(0).ok
    assert session.close().ok


def destructor_timeout(h, kind):
    session = h.open()
    operation = h.submit(session) if kind == "operation" else h.model(session)
    h.controls.timeout(3)
    if kind == "model":
        assert not operation.advance(0).execution.complete
    del session, operation
    gc.collect()
    assert h.controls.counter("calls:event_wait") >= 4
    h.reopen()


def lazy_resume_failure(h, method):
    session = h.open()
    model = h.model(session)
    assert model.close(0).ok
    h.controls.fail("module_load" if method == "submit" else "get_kernel", code=6)
    if method == "submit":
        operation = h.submit(session)
        assert operation.status.primary == 6 and operation.status.complete
        assert operation.close(0).primary == 6
    else:
        try:
            session.memory_info()
        except h.BindingError as error:
            assert error.status.primary == 6, error.status
        else:
            raise AssertionError("lazy resume replaced or hid its primary error")
    h.blocked_work(lambda: h.submit(session))
    h.blocked_work(lambda: h.model(session))
    h.blocked_work(session.memory_info)
    assert session.close().primary == 6
    assert session.close().primary == 6
    h.reopen()


def session_create_failure(h, name, occurrence):
    h.controls.fail(name, occurrence, code=6)
    try:
        h.open()
    except h.BindingError as error:
        assert error.status.primary == 6 and error.status.complete
    else:
        raise AssertionError(f"session creation lost {name}:{occurrence}")
    h.reopen()


def model_create_failure(h, name):
    session = h.open()
    h.controls.fail(name, code=6)
    model = h.model(session)
    assert model.status.execution.primary == 6 and model.status.terminal
    assert model.close(0).primary == 6
    assert model.close(0).primary == 6
    # A failed device open leaves the fake's NEXT-open selection unconsumed.
    h.controls.select_case("")
    operation = h.submit(session)
    assert operation.close(0).ok
    assert session.close().ok


def partial_submission(h, name, occurrence):
    session = h.open()
    h.controls.fail(name, occurrence, code=6)
    operation = h.submit(session)
    status = operation.status
    assert status.primary == 6, (name, occurrence, status)
    assert session.pending_operations() == (operation,)
    h.no_output(operation)
    queued = h.controls.counter("events")
    if queued:
        h.controls.timeout(1)
        result = operation.close(0)
        assert not result.complete and result.primary == 6
        assert h.controls.counter("events") == queued
        assert session.pending_operations() == (operation,)
        assert not session.close().complete
        h.blocked_open()
    result = operation.close(0)
    assert result.complete and result.primary == 6 and result.cleanup == 0
    assert operation.close(0) == result
    assert session.pending_operations() == ()
    h.no_output(operation)
    assert session.close().ok


def invalid_address(h, mode, validation):
    session = h.open()
    h.controls.bad_address(mode)
    operation = h.submit(session)
    assert operation.status.validation == validation
    assert operation.close(0).complete
    assert h.controls.counter("calls:enqueue") == 0
    h.no_output(operation)
    assert session.close().ok


def asynchronous_failure(h, ordinal):
    session = h.open()
    h.controls.async_failure(ordinal, code=6)
    h.controls.fail("cleanup")
    operation = h.submit(session)
    result = operation.close(0)
    assert result.complete and result.primary == 6 and result.cleanup == 10
    assert operation.close(0) == result
    h.no_output(operation)
    h.blocked_work(lambda: h.submit(session))
    closed = session.close()
    assert closed.complete and closed.primary == 0 and closed.cleanup == 10
    assert session.close() == closed
    h.no_output(operation)
    h.blocked_open(poison=True)


def transient_event_failure(h, name):
    session = h.open()
    operation = h.submit(session)
    h.controls.fail(name)
    result = operation.close(0)
    assert not result.complete and result.primary == 6 and result.cleanup == 0
    assert h.controls.counter("buffers") == 3
    assert session.pending_operations() == (operation,)
    h.no_output(operation)
    result = operation.close(0)
    assert result.complete and result.primary == 6 and result.cleanup == 0
    assert operation.close(0) == result
    assert session.pending_operations() == ()
    h.no_output(operation)
    assert session.close().ok
    h.no_output(operation)


def profile_failure(h, occurrence):
    session = h.open()
    h.controls.fail("profiling", occurrence)
    operation = h.submit(session)
    assert operation.close(0).ok
    trace = operation.trace()
    assert trace["event_profile_results"][occurrence - 1] == 9
    assert set(trace["event_profiles"][occurrence - 1].values()) == {0}
    assert h.controls.counter("calls:profiling") == 5
    assert session.close().ok


def explicit_operation_cleanup(h, name, occurrence):
    session = h.open()
    operation = h.submit(session)
    h.controls.fail(name, occurrence)
    result = operation.close(0)
    assert result.complete and result.primary == 0 and result.cleanup == 10
    assert operation.close(0) == result
    h.no_output(operation)
    h.blocked_work(lambda: h.submit(session))
    closed = session.close()
    assert closed.complete and closed.primary == 0 and closed.cleanup == 10
    assert session.close() == closed
    h.no_output(operation)
    h.blocked_open(poison=True)


def explicit_session_cleanup(h, name):
    session = h.open()
    h.controls.fail(name)
    result = session.close()
    assert result.complete and result.primary == 0 and result.cleanup == 10
    assert session.close() == result
    h.blocked_open(poison=True)


def destructor_cleanup(h, kind, name):
    session = h.open()
    if kind == "session":
        reference = weakref.ref(session)
        h.controls.fail(name)
        del session
        gc.collect()
        assert reference() is None
    else:
        operation = h.submit(session) if kind == "operation" else h.model(session)
        h.controls.timeout(2)
        if kind == "model":
            assert not operation.advance(0).execution.complete
        del session
        gc.collect()
        h.controls.fail(name)
        del operation
        gc.collect()
    h.blocked_open(poison=True)


def suspension_cleanup(h):
    session = h.open()
    h.controls.fail("device_release")
    model = session.model(h.case)
    assert model.status.execution.cleanup == 10 and model.status.terminal
    assert model.close(0).cleanup == 10
    assert session.close().cleanup == 10
    h.blocked_open(poison=True)


def creation_and_cleanup_failure(h):
    h.controls.fail("get_kernel", code=6)
    h.controls.fail("device_release")
    try:
        h.open()
    except h.BindingError as error:
        assert error.status.primary == 6 and error.status.cleanup == 10
    else:
        raise AssertionError("failed creation lost its primary/cleanup status")
    h.blocked_open(poison=True)


def memory_query_failure(h):
    session = h.open()
    h.controls.fail("memory_info", code=6)
    try:
        session.memory_info()
    except h.BindingError as error:
        assert error.status.primary == 6
    else:
        raise AssertionError("memory query failure was hidden")
    assert session.close().ok


def copied_bytes_and_timeout(h, m, n, k):
    session = h.open()
    a, b = h.tensors(m, n, k)
    expected_a, expected_b = bytes(a.data), bytes(b.data)
    operation = session.submit(a, b)
    a.data[:] = bytes([0xAB] * len(a.data))
    b.data[:] = bytes([0xCD] * len(b.data))
    del a, b
    gc.collect()
    assert h.controls.counter("writes_observed") == 0
    h.no_output(operation)
    h.controls.timeout(1)
    result = operation.close(123)
    assert not result.complete and result.primary == 7
    assert h.controls.counter("last_timeout_ns") == 123
    assert h.controls.counter("buffers") == 3 and h.controls.counter("events") == 5
    assert session.pending_operations() == (operation,)
    assert operation.close(0).ok
    assert operation.output_words() == tuple(0x3F800000 + i for i in range(m * n))
    capture, = h.controls.captures
    assert capture["a_hex"] == expected_a.hex() and capture["b_hex"] == expected_b.hex()
    assert capture["args_hex"] == operation.trace()["argument_bytes"]
    assert capture["grid"] == [n // 4, m // 8, 1]
    assert capture["block"] == [4, 1, 1] and capture["cluster"] == [1, 1, 1]
    assert capture["lmem"] == 0
    saved = operation.output_bytes()
    assert session.close().ok and operation.output_bytes() == saved


def frozen_model(h, case):
    session = h.open()
    assert set(h.native.fixture_cases()) == {
        f"{dtype}-{name}" for dtype in FORMATS for name in MODEL_NAMES}
    model = h.model(session, case)
    h.controls.timeout(1)
    status = model.advance(0)
    assert not status.terminal and status.execution.primary == 7
    assert session.pending_operations() == (model,)
    h.no_output(model)
    assert model.advance(0).ok
    assert model.close(0).ok
    assert session.pending_operations() == ()
    output = model.output_bytes()
    captures = h.controls.captures
    assert len(captures) == 3 and h.controls.counter("fixture_inputs_checked") == 3
    assert [row["stage"] for row in captures] == [0, 1, 2]
    assert all(row["fixture"] == case and row["inputs_validated"] for row in captures)
    assert output.hex() == captures[1]["output_hex"] + captures[2]["output_hex"]
    assert len(output) == 256
    assert isinstance(model.record(0), dict)
    assert session.close().ok and model.output_bytes() == output


def model_response_corruption(h, stage, expected):
    session = h.open()
    h.controls.corrupt_response(stage)
    model = h.model(session)
    status = model.advance(0)
    assert status.terminal and status.status == expected, status
    assert model.close(0).complete
    h.no_output(model)
    assert h.controls.counter("response_corruptions") == 1
    assert session.close().ok


def fork_orphaning(h, kind):
    session, status = h.native.session_open(h.bundle)
    assert status["complete"] and not status["primary"]
    if kind == "operation":
        operation = h.native.operation_new()
        h.native.submit_into(session, operation, 8, 4, 8, bytes(128), bytes(64), 0x7FC0DEAD)
        close = h.native.operation_close
    else:
        h.controls.select_case(h.case)
        operation = h.native.model_new()
        h.native.model_create_into(session, operation, h.case, 0x7FC0DEAD)
        close = h.native.model_close
    expected = h.controls.counters
    readfd, writefd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(readfd)
        signal.alarm(5)
        try:
            try:
                close(operation, 0)
            except RuntimeError as error:
                assert "fork" in str(error)
            else:
                raise AssertionError("child reused an inherited native capsule")
            try:
                h.open()
            except h.BindingError as error:
                assert error.kind == "process"
            else:
                raise AssertionError("child reused the inherited Python runtime")
            del session, operation
            gc.collect()
            assert h.controls.counters == expected, (h.controls.counters, expected)
            os.write(writefd, b"pass")
            os._exit(0)
        except BaseException as error:
            os.write(writefd, repr(error).encode()[:4096])
            os._exit(1)
    os.close(writefd)
    try:
        outcome = os.read(readfd, 4096)
        _, status = os.waitpid(pid, 0)
    finally:
        os.close(readfd)
    assert status == 0 and outcome == b"pass", (status, outcome)
    assert close(operation, 0)["complete"]
    assert h.native.session_close(session)["complete"]


def publication_failure(h, method):
    from vortex_ai import _api
    session = h.open()
    if method == "submit":
        call, arguments = session.submit, h.tensors()
        marker, increment = "calls:enqueue", 5
    elif method == "model":
        h.controls.select_case(h.case)
        call, arguments = session.model, (h.case,)
        marker, increment = "calls:device_open", 1
    elif method in ("wait", "close"):
        operation = h.submit(session)
        call, arguments = getattr(operation, method), (0,)
        marker, increment = ("reads_observed", 1) if method == "wait" else ("calls:queue_release", 1)
    else:
        operation = h.model(session)
        call, arguments = getattr(operation, method.removeprefix("model_")), (0,)
        marker, increment = ("launches_observed", 3) if method == "model_advance" else ("calls:device_release", 1)
    before = h.controls.counter(marker)
    # The actual compiled call has returned before Python converts its status.
    with mock.patch.object(_api, "_execution", side_effect=MemoryError("status publication")) as publish:
        try:
            call(*arguments)
        except MemoryError as error:
            pending = session.pending_operations()
            assert len(pending) == 1
            assert error.operation is pending[0] and error.session is session
        else:
            raise AssertionError("the scripted publication failure was hidden")
        assert publish.call_count == 1
    assert h.controls.counter(marker) == before + increment
    publish.side_effect = None
    del publish, call, arguments
    operation, = session.pending_operations()
    if method in ("submit", "model"):
        reference = weakref.ref(session)
        del session
        gc.collect()
        assert reference() is None
        h.blocked_open()
        assert h.controls.counter("devices") == 1
        assert operation.close(0).ok
        h.reopen()
    else:
        assert operation.close(0).ok
        assert session.pending_operations() == ()
        assert session.close().ok
    h.metrics = {"scripted_publication_memory_errors": 1, "real_native_progress": increment,
                 "progress_counter": marker, "fault_site": "Python _execution conversion"}


register("overlap_rejected_before_open_and_submit", overlap)
register("native_second_submission_reuses_capsule_only_after_close", native_second_submission)
register("pending_owner_survives_wait_and_gc", pending_after_wait)
register("orphaned_operation_retains_lease_through_wait_and_timeout", orphaned_operation)
register("model_handoff_and_lazy_resume", model_handoff)
register("session_close_preserves_independent_model", suspended_session_close)
register("rejected_empty_owners_preserve_state_errors_and_recovery", rejected_empty_owner_state)
register("successful_wait_blocks_model_handoff", waited_operation_blocks_handoff)
register("suspended_session_competes_with_new_owner", suspended_session_competes)
register("incomplete_model_close_retains_lease", incomplete_model_close)
for kind in ("operation", "model"):
    register(f"{kind}_destructor_drains_finite_timeouts", destructor_timeout, kind)
    register(f"fork_orphans_{kind}_capsules", fork_orphaning, kind)
for method in ("submit", "memory_info"):
    register(f"lazy_resume_{method}_preserves_primary", lazy_resume_failure, method)
for name, maximum in (("device_open", 1), ("query", 7), ("module_load", 1), ("get_kernel", 1)):
    for occurrence in range(1, maximum + 1):
        register(f"session_create_{name}_{occurrence}", session_create_failure, name, occurrence)
for name in ("device_open", "query", "module_load", "get_kernel", "memory_info"):
    register(f"model_create_{name}", model_create_failure, name)
for name, maximum in (("queue_create", 1), ("buffer_create", 3), ("buffer_address", 3),
                      ("enqueue_write", 3), ("enqueue_launch", 1), ("enqueue_read", 1)):
    for occurrence in range(1, maximum + 1):
        register(f"partial_submit_{name}_{occurrence}", partial_submission, name, occurrence)
for mode, validation in ((1, "misaligned_address"), (2, "aliasing"), (3, "address_out_of_range")):
    register(f"address_{validation}", invalid_address, mode, validation)
for ordinal in range(1, 6):
    register(f"async_primary_and_cleanup_{ordinal}", asynchronous_failure, ordinal)
    register(f"profiling_failure_{ordinal}", profile_failure, ordinal)
for name in ("event_wait", "event_value"):
    register(f"transient_{name}_retains_owner", transient_event_failure, name)
for name, maximum in (("event_release", 5), ("queue_release", 1), ("buffer_release", 3)):
    for occurrence in range(1, maximum + 1):
        register(f"explicit_cleanup_{name}_{occurrence}", explicit_operation_cleanup, name, occurrence)
for name in ("kernel_release", "module_release", "device_release"):
    register(f"explicit_session_cleanup_{name}", explicit_session_cleanup, name)
    register(f"destructor_session_cleanup_{name}", destructor_cleanup, "session", name)
for name in ("event_release", "queue_release", "buffer_release", "device_release"):
    register(f"destructor_operation_cleanup_{name}", destructor_cleanup, "operation", name)
for name in ("event_release", "device_release"):
    register(f"destructor_model_cleanup_{name}", destructor_cleanup, "model", name)
register("suspension_cleanup_is_sticky", suspension_cleanup)
register("failed_creation_with_cleanup_poison", creation_and_cleanup_failure)
register("memory_query_preserves_primary", memory_query_failure)
for dtype in FORMATS:
    for shape in SHAPES:
        register("copied_bytes_timeout_" + "_".join(map(str, shape)), copied_bytes_and_timeout,
                 *shape, dtype=dtype)
    for name in MODEL_NAMES:
        register(f"frozen_model_{name}", frozen_model, f"{dtype}-{name}", dtype=dtype)
for stage, result in ((0, "hidden_mismatch"), (1, "output_mismatch"), (2, "output_mismatch")):
    register(f"model_response_corruption_{stage}", model_response_corruption, stage, result)
for method in ("submit", "model", "wait", "close", "model_advance", "model_close"):
    register(f"publication_memoryerror_{method}_retains_recoverable_owner", publication_failure, method)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@unittest.skipUnless(sys.platform == "linux" and sys.implementation.name == "cpython"
                     and sys.version_info[:2] == (3, 12)
                     and not sysconfig.get_config_var("Py_GIL_DISABLED"),
                     "the P05 native binding supports GIL-enabled Linux CPython 3.12")
class NativeBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.started = time.monotonic()
        configured = os.environ.get("P05_NATIVE_TEST_WORKDIR")
        if configured:
            cls.work = Path(configured).absolute()
            cls.work.mkdir(parents=True, exist_ok=True)
            if any(cls.work.iterdir()):
                raise ValueError("P05_NATIVE_TEST_WORKDIR must be new or empty")
        else:
            temporary = tempfile.TemporaryDirectory(prefix="p05-native-host-only-")
            cls.addClassCleanup(temporary.cleanup)
            cls.work = Path(temporary.name)
        cls.report = {"scope": SCOPE, "scenario_count": len(SCENARIOS), "builds": {}, "results": [],
                      "python": sys.version, "child_timeout_seconds": 20,
                      "sources": {str(Path(__file__).resolve().relative_to(ROOT)): digest(__file__)}}
        cls.addClassCleanup(cls.finish_report)
        cls.snapshot = cls.work / "test_p05_native_binding.snapshot.py"
        shutil.copyfile(__file__, cls.snapshot)
        cls.runtimes = {}
        for dtype in FORMATS:
            began = time.monotonic()
            runtime = build_test_runtime(cls.work / dtype, dtype=dtype)
            cls.runtimes[dtype] = runtime
            manifest = json.loads((runtime.bundle / "manifest.json").read_text())
            cls.report["builds"][dtype] = {
                "seconds": round(time.monotonic() - began, 3),
                "extension_sha256": digest(runtime.extension),
                "manifest_sha256": digest(runtime.bundle / "manifest.json"),
                "source_sha256": manifest["source_sha256"],
                "binding_sources": manifest["binding_sources"],
                "commands": [list(command) for command in runtime.commands],
            }
            cls.finish_report()

    @classmethod
    def finish_report(cls):
        cls.report["seconds"] = round(time.monotonic() - cls.started, 3)
        cls.report["completed"] = len(cls.report["results"])
        cls.report["passed"] = sum(row["passed"] for row in cls.report["results"])
        write_json(cls.work / "results.json", cls.report)

    def run_scenario(self, name):
        dtype, _, _ = SCENARIOS[name]
        runtime = self.runtimes[dtype]
        source = ("import runpy, sys\n"
                  f"sys.argv = [{str(self.snapshot)!r}, '--child', {name!r}]\n"
                  f"runpy.run_path({str(self.snapshot)!r}, run_name='__main__')\n")
        child = self.work / "children" / name
        child.mkdir(parents=True)
        (child / "launcher.py").write_text(source, encoding="utf-8")
        write_json(child / "command.json", {
            "command": [sys.executable, "-c", source], "cwd": str(runtime.root),
            "pythonpath": runtime.environment()["PYTHONPATH"], "timeout_seconds": 20,
            "test_snapshot_sha256": digest(self.snapshot),
        })
        began = time.monotonic()
        try:
            result = runtime.run_python(source, timeout=20, check=False)
            row = {"name": name, "format": dtype,
                   "passed": result.returncode == 0 and not result.stderr,
                   "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        except subprocess.TimeoutExpired as error:
            row = {"name": name, "format": dtype, "passed": False, "returncode": None,
                   "stdout": str(error.stdout or ""), "stderr": str(error.stderr or ""),
                   "error": "child exceeded 20-second deadline"}
        row["seconds"] = round(time.monotonic() - began, 3)
        (child / "stdout.log").write_text(row["stdout"], encoding="utf-8")
        (child / "stderr.log").write_text(row["stderr"], encoding="utf-8")
        if row["passed"]:
            try:
                row["observations"] = json.loads(row["stdout"])
            except (TypeError, ValueError) as error:
                row.update(passed=False, error=f"invalid child result: {error}")
        self.report["results"].append(row)
        self.finish_report()
        self.assertTrue(row["passed"], f"Host-only scenario {name} failed:\n{row['stdout']}\n{row['stderr']}")


def make_test(name):
    def test(self):
        self.run_scenario(name)
    test.__name__ = f"test_{name}"
    return test


for _name in SCENARIOS:
    setattr(NativeBindingTests, f"test_{_name}", make_test(_name))


def child_main(name):
    if sys.flags.optimize:
        raise RuntimeError("native fault checks require Python assertions enabled")
    dtype, function, arguments = SCENARIOS[name]
    if dtype != os.environ["P05_TEST_DTYPE"]:
        raise RuntimeError("scenario/extension format mismatch")
    checks = ChildChecks(dtype)
    function(checks, *arguments)
    checks.done()
    print(json.dumps({"scope": SCOPE, "scenario": name, "format": dtype,
                      "counters": checks.controls.counters, "metrics": checks.metrics}, sort_keys=True))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        child_main(sys.argv[2])
    else:
        unittest.main()
