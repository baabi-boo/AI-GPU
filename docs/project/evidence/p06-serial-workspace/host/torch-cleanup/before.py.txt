# SPDX-License-Identifier: Apache-2.0
"""Explicit optional PyTorch tests through the compiled HOST-ONLY native boundary.

The existing fault runtime supplies synthetic words or frozen fixture responses.
It executes no SimX backend or accelerator arithmetic. This test deliberately
uses its separately pinned test extension, never a production wheel or bundle.
It must be invoked explicitly in an environment containing the pinned PyTorch;
ordinary test discovery does not import Torch or build this additional runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


SCOPE = "host-only-real-pytorch-compiled-native-fault-runtime"
SCENARIOS = ("matmul_shapes", "fixed_models", "transient_timeout", "matmul_deadline",
             "model_deadline", "partial_submit", "async_failure", "cleanup_failure",
             "model_mismatch")
MODEL_NAMES = ("seeded_dense", "negated_dense", "zero", "signed_basis", "split_boundary")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def child(name):
    if sys.flags.optimize:
        raise RuntimeError("host boundary assertions require a non-optimized interpreter")
    import struct
    import torch
    from p05_test_runtime import FaultControls
    from vortex_ai import BindingError, Session, _native
    from vortex_ai.torch_ops import TorchSession

    bundle, fmt = os.environ["P05_TEST_BUNDLE"], os.environ["P05_TEST_DTYPE"]
    controls = FaultControls.activate(bundle)
    session = Session.open(bundle)
    adapter = TorchSession(session, timeout_seconds=0.05 if name.endswith("deadline") else 5)
    dtype = torch.float16 if fmt == "fp16" else torch.bfloat16
    metrics = {}

    def tensors(m=8, n=4, k=8):
        a = torch.frombuffer(bytearray([0x12] * (m * k * 2)), dtype=dtype).reshape(m, k)
        b = torch.frombuffer(bytearray([0x34] * (k * n * 2)), dtype=dtype).reshape(n, k).t()
        return a, b

    def raw_matmul(m=8, n=4, k=8):
        return torch.ops.vortex_ai.matmul_v1(*tensors(m, n, k), adapter.token, 0x7FC0DEAD)

    def raw_model(case):
        controls.select_case(case)
        return torch.ops.vortex_ai.fixed_mlp_v1(case, adapter.token, 0xDEADBEEF)

    def output(value, shape):
        operation = adapter.last_operation
        assert type(value) is torch.Tensor and value.device.type == "cpu"
        assert value.dtype == torch.float32 and tuple(value.shape) == shape
        assert not value.requires_grad and value.storage_offset() == 0
        assert not session.pending_operations(), "operator returned before explicit native close"
        assert operation.close(0).ok
        actual = struct.pack(f"<{value.numel()}i", *value.view(torch.int32).flatten().tolist())
        assert actual == operation.output_bytes()
        return actual

    def rejected(call):
        try:
            call()
        except BindingError as error:
            assert error.session is session and error.adapter is adapter
            return error
        raise AssertionError("scripted native error returned a successful tensor")

    def no_output(operation):
        try:
            operation.output_bytes()
        except BindingError:
            return
        raise AssertionError("failed or incomplete native owner published output")

    saved = []
    if name == "matmul_shapes":
        for m, n, k in ((8, 4, 8), (8, 4, 16), (16, 8, 16)):
            value = raw_matmul(m, n, k)
            bits = output(value, (m, n))
            assert bits == struct.pack(f"<{m*n}I", *(0x3F800000 + i for i in range(m*n)))
            capture = controls.captures[-1]
            assert capture["a_hex"] == (bytes([0x12]) * (m*k*2)).hex()
            assert capture["b_hex"] == (bytes([0x34]) * (k*n*2)).hex()
            assert capture["args_hex"] == adapter.last_operation.trace()["argument_bytes"]
            assert capture["grid"] == [n//4, m//8, 1]
            saved.append((value, bits))
        assert len(controls.captures) == 3
    elif name == "fixed_models":
        for family in MODEL_NAMES:
            case = fmt + "-" + family
            value = raw_model(case)
            bits = output(value, (16, 4))
            captures = controls.captures[-3:]
            assert [row["stage"] for row in captures] == [0, 1, 2]
            assert all(row["fixture"] == case and row["inputs_validated"] for row in captures)
            assert bits.hex() == captures[1]["output_hex"] + captures[2]["output_hex"]
            assert adapter.last_operation.status.ok
            saved.append((value, bits))
        assert controls.counter("fixture_inputs_checked") == 15
    elif name == "transient_timeout":
        controls.timeout(1)
        output(raw_matmul(), (8, 4))
        assert controls.counter("calls:event_wait") >= 2
        # Successful native cleanup can finish with a zero-time event poll.
        assert 0 <= controls.counter("last_timeout_ns") <= 100_000_000
    elif name in ("matmul_deadline", "model_deadline"):
        controls.timeout(1_000_000_000)
        error = rejected(raw_matmul if name == "matmul_deadline"
                         else lambda: raw_model(fmt + "-seeded_dense"))
        assert error.kind == "timeout"
        operation = adapter.last_operation
        assert operation is not None and session.pending_operations() == (operation,)
        no_output(operation)
        before = controls.counter("calls:enqueue")
        try:
            adapter.close()
        except BindingError:
            pass
        else:
            raise AssertionError("adapter detached with pending native ownership")
        assert controls.counter("calls:enqueue") == before
        assert 0 < controls.counter("last_timeout_ns") <= 100_000_000
        controls.timeout(0)
        if name == "model_deadline":
            for _ in range(4):
                if operation.advance(0).terminal:
                    break
            assert operation.status.ok
        assert operation.close(0).ok
        assert not session.pending_operations()
        metrics["recovered_output_bytes"] = len(operation.output_bytes())
        output(raw_matmul(), (8, 4))
    elif name in ("partial_submit", "async_failure"):
        if name == "partial_submit":
            controls.fail("enqueue", occurrence=3, code=6)
        else:
            controls.async_failure(4, code=6)
        error = rejected(raw_matmul)
        operation = adapter.last_operation
        assert error.operation is operation and session.pending_operations() == (operation,)
        no_output(operation)
        result = operation.close(0)
        assert result.complete and result.primary == 6 and result.cleanup == 0
        assert not session.pending_operations()
        no_output(operation)
        controls.clear_failures()
        controls.async_failure(0)
        output(raw_matmul(), (8, 4))
    elif name == "cleanup_failure":
        controls.fail("event_release", occurrence=1)
        error = rejected(raw_matmul)
        operation = adapter.last_operation
        assert error.operation is operation
        result = operation.close(0)
        assert result.complete and result.primary == 0 and result.cleanup == 10
        no_output(operation)
        before = controls.counter("calls:enqueue")
        blocked = rejected(raw_matmul)
        # Even a state-rejected submission may have published an empty owner
        # into the binding's recovery inventory before native entry rejects it.
        if blocked.operation is not None:
            assert blocked.operation.close(0).complete
        assert controls.counter("calls:enqueue") == before
        metrics["process_recovery_required"] = True
    elif name == "model_mismatch":
        controls.corrupt_response(0)
        rejected(lambda: raw_model(fmt + "-seeded_dense"))
        operation = adapter.last_operation
        assert session.pending_operations() == (operation,)
        assert operation.status.terminal and operation.status.status == "hidden_mismatch"
        no_output(operation)
        assert operation.close(0).complete
        no_output(operation)
        controls.corrupt_response(-1)
        assert controls.counter("response_corruptions") == 1
        output(raw_matmul(), (8, 4))
    else:
        raise ValueError(name)

    adapter.close()
    assert session.close().ok
    if name == "cleanup_failure":
        before = controls.counter("calls:device_open")
        try:
            Session.open(bundle)
        except BindingError as error:
            assert error.kind == "state" and "cleanup failed" in str(error)
        else:
            raise AssertionError("process cleanup poison was bypassed")
        assert controls.counter("calls:device_open") == before
    for value, expected in saved:
        assert struct.pack(f"<{value.numel()}i", *value.view(torch.int32).flatten().tolist()) == expected
    controls.assert_no_resources()
    assert controls.counter("max_live_devices") <= 1
    assert controls.counter("input_copy_mismatches") == 0
    print(json.dumps({"scope": SCOPE, "scenario": name, "format": fmt, "outcome": "pass",
                      "torch_version": str(torch.__version__), "extension_file": _native.__file__,
                      "counters": controls.counters, "metrics": metrics}, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--format", choices=("fp16", "bf16"), default="fp16")
    args = parser.parse_args()
    root = args.source_dir.resolve(strict=True)
    work = args.work_dir.absolute()
    if work.exists() or not work.parent.is_dir():
        raise ValueError("work directory must be fresh under an existing parent")
    if shutil.disk_usage(work.parent).free < 10 * 1024**3:
        raise RuntimeError("host boundary probe requires a 10 GiB disk reserve")
    sys.path.insert(0, str(root / "ci/project"))
    from p05_test_runtime import build_test_runtime
    work.mkdir(mode=0o700)
    snapshot = work / "test.snapshot.py"
    shutil.copyfile(__file__, snapshot)
    report = {"schema_version": 1, "scope": SCOPE, "acceptance_claimed": False,
              "native_accelerator_execution": "not_run", "backend_execution": "not_run",
              "format": args.format, "python_version": sys.version,
              "scenario_count": len(SCENARIOS), "child_timeout_seconds": 30,
              "test_sha256": digest(snapshot), "results": [], "outcome": "running"}
    started = time.monotonic()
    try:
        runtime = build_test_runtime(work / "runtime", dtype=args.format)
        report["build"] = {"extension_sha256": digest(runtime.extension),
                           "manifest_sha256": digest(runtime.bundle / "manifest.json"),
                           "manifest": json.loads((runtime.bundle / "manifest.json").read_text()),
                           "commands": [list(command) for command in runtime.commands]}
        (work / "children").mkdir()
        for scenario in SCENARIOS:
            target = work / "children" / scenario
            target.mkdir()
            source = ("import runpy, sys\n"
                      f"sys.argv = [{str(snapshot)!r}, '--child', {scenario!r}]\n"
                      f"runpy.run_path({str(snapshot)!r}, run_name='__main__')\n")
            (target / "launcher.py").write_text(source)
            write_json(target / "command.json", {"argv": [sys.executable, "-c", source],
                "cwd": str(runtime.root), "pythonpath": runtime.environment()["PYTHONPATH"],
                "timeout_seconds": 30, "scope": SCOPE})
            began = time.monotonic()
            try:
                result = subprocess.run([sys.executable, "-c", source], cwd=runtime.root,
                                        env=runtime.environment(), capture_output=True,
                                        timeout=30, check=False)
                row = {"scenario": scenario, "exit_code": result.returncode,
                       "outcome": "pass" if result.returncode == 0 and not result.stderr else "fail"}
                stdout, stderr = result.stdout, result.stderr
            except subprocess.TimeoutExpired as error:
                row = {"scenario": scenario, "exit_code": None, "outcome": "fail", "reason": "30-second child timeout"}
                stdout, stderr = error.stdout or b"", error.stderr or b""
            (target / "stdout.log").write_bytes(stdout)
            (target / "stderr.log").write_bytes(stderr)
            if row["outcome"] == "pass":
                try:
                    observation = json.loads(stdout)
                    expected = {"scope": SCOPE, "scenario": scenario,
                                "format": args.format, "outcome": "pass"}
                    if type(observation) is not dict or any(observation.get(key) != value
                                                           for key, value in expected.items()):
                        row.update(outcome="fail", reason="child observation identity differs")
                    else:
                        row["observations"] = observation
                except (ValueError, UnicodeError) as error:
                    row.update(outcome="fail", reason="invalid child JSON: " + str(error))
            row["seconds"] = round(time.monotonic() - began, 3)
            row["stdout_sha256"], row["stderr_sha256"] = digest(target / "stdout.log"), digest(target / "stderr.log")
            report["results"].append(row)
            print(scenario + ": " + row["outcome"], flush=True)
            write_json(work / "report.json", report)
        report["outcome"] = "pass" if all(row["outcome"] == "pass" for row in report["results"]) else "fail"
    except BaseException as error:
        report.update(outcome="fail", reason=f"{type(error).__name__}: {error}")
        raise
    finally:
        report["seconds"] = round(time.monotonic() - started, 3)
        report["completed"] = len(report["results"])
        write_json(work / "report.json", report)
    return 0 if report["outcome"] == "pass" else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        child(sys.argv[2])
    else:
        raise SystemExit(main())
