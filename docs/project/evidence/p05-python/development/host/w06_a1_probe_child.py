"""Independent W06 host-only probes; never establishes accelerator execution."""

import json
import os
from pathlib import Path
import sys

from vortex_ai import BindingError, Session, Tensor, _native


LIBRARIES = (
    "libramulator.so", "libramulator-vortex.so", "libvortex.so",
    "libsimx.so", "libvortex-simx.so",
)
observations = []


def project_maps():
    return sorted({line.split(maxsplit=5)[-1] for line in Path("/proc/self/maps").read_text().splitlines()
                   if any("/" + name in line for name in LIBRARIES)})


def native_state(label, call, fragment):
    try:
        call()
    except BlockingIOError as error:
        assert fragment in str(error), (label, str(error))
        observations.append({"label": label, "native_exception": type(error).__name__,
                             "message": str(error)})
    else:
        raise AssertionError(label + " did not reject with native BlockingIOError")


def public_state(label, call, session, *, operation=None, native_cause=True):
    try:
        call()
    except BindingError as error:
        assert error.kind == "state", (label, error.kind)
        assert error.session is session, label
        if operation is not None:
            assert error.operation is operation, label
        if native_cause:
            assert isinstance(error.__cause__, BlockingIOError), (label, error.__cause__)
        observations.append({"label": label, "kind": error.kind,
                             "cause": type(error.__cause__).__name__,
                             "message": str(error), "session_retained": True,
                             "operation_retained": error.operation is not None})
        return error
    raise AssertionError(label + " did not reject with BindingError(kind=state)")


def tensors():
    return (Tensor(bytes(128), dtype="fp16", shape=(8, 8), layout="row_major"),
            Tensor(bytes(64), dtype="fp16", shape=(8, 4), layout="column_major"))


def pending_close(bundle, controls):
    session = Session.open(bundle)
    active = session.submit(*tensors())
    status = session.close()
    assert status.primary == 7 and not status.complete
    before = controls.counter("calls:memory_info")
    public_state("public incomplete-close memory_info", session.memory_info, session, native_cause=False)
    native_state("native incomplete-close memory_info",
                 lambda: _native.session_memory_info(session._handle), "closing or closed")
    empty_operation = _native.operation_new()
    empty_model = _native.model_new()
    native_state("native incomplete-close submit",
                 lambda: _native.submit_into(session._handle, empty_operation,
                                             8, 4, 8, bytes(128), bytes(64), 0x7FC0DEAD),
                 "closing or closed")
    native_state("native incomplete-close model",
                 lambda: _native.model_create_into(session._handle, empty_model,
                                                   "fp16-seeded_dense", 0x7FC0DEAD),
                 "closing or closed")
    assert controls.counter("calls:memory_info") == before
    assert _native.operation_close(empty_operation, 0)["complete"]
    assert _native.model_close(empty_model, 0)["complete"]
    assert active.close(0).ok
    assert session.close().ok


def lazy_resume(bundle, controls, method):
    session = Session.open(bundle)
    controls.select_case("fp16-seeded_dense")
    model = session.model("fp16-seeded_dense")
    assert model.close(0).ok
    controls.fail("module_load" if method == "submit" else "get_kernel", code=6)
    if method == "submit":
        failed = session.submit(*tensors())
        assert failed.status.primary == 6 and failed.status.complete
        assert failed.close(0).primary == 6
    else:
        try:
            session.memory_info()
        except BindingError as error:
            assert error.status.primary == 6 and error.session is session
            observations.append({"label": "lazy resume primary", "primary": error.status.primary,
                                 "kind": error.kind})
        else:
            raise AssertionError("lazy resume primary failure disappeared")
    for label, call in (("submit", lambda: session.submit(*tensors())),
                        ("model", lambda: session.model("fp16-seeded_dense")),
                        ("memory_info", session.memory_info)):
        error = public_state("lazy resume " + method + " then " + label, call, session)
        assert "closing or closed" in str(error.__cause__)
        if error.operation is not None:
            assert error.operation.close(0).complete
    assert session.close().primary == 6
    assert session.close().primary == 6


def empty_owners(bundle, controls):
    session = Session.open(bundle)
    active = session.submit(*tensors())
    operation_error = public_state("second submit", lambda: session.submit(*tensors()), session)
    empty = operation_error.operation
    assert empty is not None
    native_state("native empty operation wait", lambda: _native.operation_wait(empty._handle, 0),
                 "has not been submitted")
    native_state("native empty operation trace", lambda: _native.operation_trace(empty._handle),
                 "has no native trace")
    public_state("public empty operation wait", lambda: empty.wait(0), session, operation=empty)
    public_state("public empty operation trace", empty.trace, session, operation=empty)
    assert empty.close(0).complete
    assert session.pending_operations() == (active,)
    model_error = public_state("conflicting model", lambda: session.model("fp16-seeded_dense"), session)
    empty = model_error.operation
    assert empty is not None
    native_state("native empty model advance", lambda: _native.model_advance(empty._handle, 0),
                 "has not been created")
    native_state("native empty model trace", lambda: _native.model_trace(empty._handle),
                 "has no native trace")
    native_state("native empty model record", lambda: _native.model_record(empty._handle, 0),
                 "has no native execution record")
    public_state("public empty model advance", lambda: empty.advance(0), session, operation=empty)
    public_state("public empty model trace", empty.trace, session, operation=empty)
    public_state("public empty model record", empty.record, session, operation=empty)
    assert empty.close(0).complete
    assert session.pending_operations() == (active,)
    assert active.close(0).ok
    assert session.close().ok


mode = sys.argv[1]
bundle = os.environ["P05_TEST_BUNDLE"]
assert not project_maps(), project_maps()
if mode == "path_reject":
    try:
        _native.session_open(bundle)
    except RuntimeError as error:
        assert type(error) is RuntimeError, type(error)
        assert os.environ["P05_EXPECT_PATH_ERROR"] in str(error), str(error)
        observations.append({"label": "native verifier rejected before load",
                             "exception": type(error).__name__, "message": str(error)})
    else:
        raise AssertionError("native verifier accepted loader-sensitive root")
    assert not project_maps(), project_maps()
    result = {"project_libraries_before": [], "project_libraries_after": []}
elif mode == "path_accept":
    from p05_test_runtime import FaultControls
    session, status = _native.session_open(bundle)
    assert session is not None and status["complete"] and status["primary"] == 0
    actual = _native.session_info(session)["libraries"]
    expected = tuple(str(Path(bundle).resolve() / "lib" / name) for name in LIBRARIES)
    assert tuple(actual) == expected, (actual, expected)
    assert project_maps() == sorted(expected), project_maps()
    assert _native.session_close(session)["complete"]
    controls = FaultControls(bundle)
    controls.assert_no_resources()
    result = {"project_libraries_after": project_maps(), "counters": controls.counters}
else:
    from p05_test_runtime import FaultControls
    controls = FaultControls.activate(bundle)
    if mode == "pending_close":
        pending_close(bundle, controls)
    elif mode in ("lazy_submit", "lazy_memory_info"):
        lazy_resume(bundle, controls, mode.removeprefix("lazy_"))
    elif mode == "empty_owners":
        empty_owners(bundle, controls)
    else:
        raise AssertionError("unknown probe mode: " + mode)
    assert Session.open(bundle).close().ok
    controls.assert_no_resources()
    assert controls.counter("max_live_devices") == 1
    result = {"counters": controls.counters}
print(json.dumps({"scope": "host-only-fault-injection", "mode": mode,
                  "bundle": bundle, "cwd": os.getcwd(), "build_info": _native.build_info(),
                  "observations": observations, **result}, sort_keys=True))
