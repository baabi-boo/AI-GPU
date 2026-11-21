#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Observe registered PyTorch calls through a clean installed native bundle."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.machinery
import importlib.metadata
import importlib.util
import os
from pathlib import Path
import platform
import struct
import sys
import sysconfig
import time
import traceback


def _sibling(name):
    path = Path(__file__).absolute().with_name(name + ".py")
    if path.resolve(strict=True) != path or not path.is_file():
        raise RuntimeError("installed checker helper must be a canonical sibling file: " + name)
    module_name = "_p05_torch_check_" + name
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


check = _sibling("p05_installed_check")
records = _sibling("p05_torch_records")
require = records.require


def inspect_contract(path, request):
    contract, raw = records.read_json_file(path)
    require(hashlib.sha256(raw).hexdigest() == request["framework"]["contract_sha256"],
            "copied framework contract bytes differ from the request")
    require(type(contract) is dict and type(contract.get("schema_version")) is int
            and contract["schema_version"] == 1
            and contract.get("contract_id") == "p05-torch-custom-ops-v1",
            "unsupported copied framework contract")
    records.same(contract.get("framework"), {"name": "torch", "version": records.TORCH_VERSION,
        "distribution": "cpu", "python": "3.12.14", "implementation": "CPython", "gil": True,
        "platform": "linux", "machine": "x86_64", "byteorder": "little"},
        "copied framework environment contract differs")
    operators = contract.get("operators")
    require(type(operators) is list and len(operators) == 2, "copied framework operator inventory differs")
    for operator, (name, schema) in zip(operators, records.SCHEMAS.items()):
        require(type(operator) is dict and operator.get("name") == "vortex_ai::" + name
                and operator.get("schema") == schema.removeprefix("vortex_ai::"),
                "copied framework operator schema differs")
    records.same(contract.get("qualification_per_format"), {
        "matmul_runs": 6, "model_runs": 10, "matmul_launches": 6,
        "model_launches": 30, "total_launches": 36, "event_profile_pairs": 180,
    }, "copied framework matrix differs")


def inspect_framework(request, installation, torch, adapter):
    require(platform.python_implementation() == "CPython" and sys.version_info[:3] == (3, 12, 14)
            and sys.platform == "linux" and platform.machine() == "x86_64" and sys.byteorder == "little"
            and not sysconfig.get_config_var("Py_GIL_DISABLED"),
            "framework qualification requires the pinned Linux x86_64 CPython 3.12.14 environment")
    require(str(torch.__version__) == records.TORCH_VERSION
            and torch.version.cuda is None and torch.version.hip is None,
            "installed framework is not the pinned CPU PyTorch distribution")
    prefix = Path(request["base_request"]["expected_prefix"])
    distribution = importlib.metadata.distribution("torch")
    require(distribution.version == records.TORCH_VERSION, "framework distribution version differs")
    torch_file = Path(torch.__file__)
    require(torch_file.resolve(strict=True) == torch_file and torch_file.is_relative_to(prefix)
            and torch_file.is_file()
            and distribution.locate_file("torch/__init__.py").resolve(strict=True) == torch_file,
            "framework import is outside the requested clean installation")
    extension = importlib.import_module("torch._C")
    extension_file = Path(extension.__file__)
    require(isinstance(extension.__spec__.loader, importlib.machinery.ExtensionFileLoader)
            and extension_file.resolve(strict=True) == extension_file
            and extension_file.is_relative_to(prefix) and extension_file.is_file(),
            "framework compiled extension is outside the requested clean installation")
    adapter_file = Path(adapter.__file__)
    expected = Path(installation["package_file"]).parent / "torch_ops.py"
    require(adapter_file == expected and adapter_file.resolve(strict=True) == adapter_file
            and isinstance(adapter.__spec__.loader, importlib.machinery.SourceFileLoader),
            "framework adapter did not load from the installed wheel")
    adapter_hash = hashlib.sha256(adapter_file.read_bytes()).hexdigest()
    require(adapter_hash == request["framework"]["adapter_sha256"], "installed framework adapter hash differs")
    schemas = {name: str(getattr(torch.ops.vortex_ai, name).default._schema) for name in records.SCHEMAS}
    records.same(schemas, records.SCHEMAS, "installed registered schemas differ")
    return {"version": str(torch.__version__), "distribution_version": distribution.version,
            "contract_sha256": request["framework"]["contract_sha256"],
            "adapter_file": str(adapter_file), "adapter_sha256": adapter_hash,
            "operator_schemas": schemas}


def tensor_observation(torch, tensor, *, shape, strides, dtype, physical_column=False):
    require(type(tensor) is torch.Tensor and tensor.device == torch.device("cpu")
            and tensor.layout == torch.strided and tensor.dtype == dtype
            and tuple(tensor.shape) == tuple(shape) and tuple(tensor.stride()) == tuple(strides)
            and tensor.storage_offset() == 0 and tensor.requires_grad is False
            and not tensor.is_neg() and not tensor.is_conj()
            and torch.autograd.forward_ad.unpack_dual(tensor).tangent is None,
            "observed framework tensor representation differs")
    size = tensor.element_size()
    require(size in (2, 4) and tensor.untyped_storage().nbytes() == shape[0] * shape[1] * size,
            "observed framework tensor storage extent differs")
    physical = tensor.t() if physical_column else tensor
    require(physical.is_contiguous(), "framework tensor physical order is not packed")
    integer = torch.int16 if size == 2 else torch.int32
    unsigned = 0xFFFF if size == 2 else 0xFFFFFFFF
    values = [word & unsigned for word in physical.view(integer).reshape(-1).tolist()]
    raw = struct.pack("<" + ("H" if size == 2 else "I") * len(values), *values)
    return {"shape": list(tensor.shape), "strides": list(tensor.stride()),
            "dtype": str(tensor.dtype), "device": str(tensor.device),
            "storage_offset": tensor.storage_offset(), "requires_grad": tensor.requires_grad,
            "bytes": raw.hex()}


def _input(torch, data, shape, dtype, *, column=False):
    value = torch.frombuffer(bytearray(data), dtype=dtype).clone()
    return value.reshape(shape[1], shape[0]).t() if column else value.reshape(shape)


def run_matrix(request, api, torch, adapter_module, installation, framework, state):
    base_request = request["base_request"]
    binding = base_request["binding"]
    deadline = time.monotonic() + check.MATRIX_SECONDS
    session = state.session = api.Session.open(binding["bundle_root"])
    check.successful(session.status)
    installation["runtime_libraries"] = check.session_identity(session, base_request)
    adapter = state.adapter = adapter_module.TorchSession(session)
    matmuls, models, framework_matmuls, framework_models = [], [], [], []
    retained_outputs = []
    storage_addresses = set()
    dtype = torch.float16 if binding["format"] == "fp16" else torch.bfloat16
    previous_end = 0
    check.emit("P05_TORCH_FRAMEWORK", framework)

    def retain_output(value, observation, inputs=()):
        address = value.untyped_storage().data_ptr()
        require(address > 0 and address not in storage_addresses
                and all(address != tensor.untyped_storage().data_ptr() for tensor in inputs),
                "framework result aliases an input or an earlier live result")
        storage_addresses.add(address)
        retained_outputs.append((value, observation))

    for case in base_request["matmul_cases"]:
        m, n, k = (case[key] for key in ("m", "n", "k"))
        a = _input(torch, check.packed(case["a_words"]), (m, k), dtype)
        b = _input(torch, check.packed(case["b_words"]), (k, n), dtype, column=True)
        for iteration, poison in enumerate(check.POISONS):
            check.timeout_ns(deadline)
            require(not session.pending_operations(), "a native owner remains before a framework matmul")
            before = check.memory_info(session)
            a_observed = tensor_observation(torch, a, shape=(m, k), strides=(k, 1), dtype=dtype)
            b_observed = tensor_observation(torch, b, shape=(k, n), strides=(1, k), dtype=dtype,
                                            physical_column=True)
            result = torch.ops.vortex_ai.matmul_v1(a, b, adapter.token, poison)
            operation = state.retain(adapter.last_operation)
            require(type(operation) is api.Operation, "framework matmul did not retain its actual native owner")
            require(not session.pending_operations(), "framework matmul returned before explicit native close")
            status = check.successful(operation.status, operation)
            close_status = check.successful(operation.close(0), operation)
            state.closed.add(id(operation))
            require(not session.pending_operations(), "framework matmul returned before explicit native close")
            after = check.memory_info(session)
            actual = check.output_words(operation.output_bytes(), m * n)
            trace = operation.trace()
            native_row = {"case_id": case["id"], "iteration": iteration, "status": status,
                          "close_status": close_status, "actual_bits": actual, "trace": trace,
                          "resources": check.resources(before, after)}
            returned = tensor_observation(torch, result, shape=(m, n), strides=(n, 1), dtype=torch.float32)
            records.same(a_observed, tensor_observation(torch, a, shape=(m, k), strides=(k, 1), dtype=dtype),
                         "framework matmul mutated A")
            records.same(b_observed, tensor_observation(torch, b, shape=(k, n), strides=(1, k), dtype=dtype,
                                                        physical_column=True), "framework matmul mutated B")
            require(returned["bytes"] == operation.output_bytes().hex(),
                    "returned framework matmul bits differ from the actual native output")
            framework_row = {"case_id": case["id"], "iteration": iteration,
                             "a": a_observed, "b": b_observed, "result": returned}
            check.emit("P05_MATMUL", native_row)
            check.emit("P05_TORCH_MATMUL", framework_row)
            require(before == after, "native framework matmul resources were not restored")
            require(actual == case["expected"], "framework matmul differs from immutable fixture words")
            end = check.dispatch(trace, (m, n, k), case["format"], poison, binding["qualification_id"])
            require(previous_end <= trace["event_profiles"][0]["queued_ns"],
                    "framework matmul precedes its completed predecessor")
            previous_end = end
            retain_output(result, returned, (a, b))
            matmuls.append(native_row)
            framework_matmuls.append(framework_row)
    for case_id in base_request["model_cases"]:
        for iteration, poison in enumerate(check.POISONS):
            check.timeout_ns(deadline)
            require(not session.pending_operations(), "a native owner remains before a framework model")
            result = torch.ops.vortex_ai.fixed_mlp_v1(case_id, adapter.token, poison)
            model = state.retain(adapter.last_operation)
            require(type(model) is api.ModelOperation, "framework model did not retain its actual native owner")
            require(not session.pending_operations(), "framework model returned before explicit native close")
            model.status.raise_for_status(model)
            check.successful(model.close(0), model)
            state.closed.add(id(model))
            model.status.raise_for_status(model)
            require(not session.pending_operations(), "framework model returned before explicit native close")
            record = model.record(iteration)
            native_row = {"case_id": case_id, "iteration": iteration, "record": record}
            returned = tensor_observation(torch, result, shape=(16, 4), strides=(4, 1), dtype=torch.float32)
            require(returned["bytes"] == model.output_bytes().hex(),
                    "returned framework model bits differ from the actual native output")
            framework_row = {"case_id": case_id, "iteration": iteration, "result": returned}
            check.emit("P05_MODEL", native_row)
            check.emit("P05_TORCH_MODEL", framework_row)
            end = check.check_model(record, model, case_id, iteration, binding)
            require(previous_end <= record["trace"]["create_begin_ns"],
                    "framework model precedes its completed predecessor")
            previous_end = end
            retain_output(result, returned)
            models.append(native_row)
            framework_models.append(framework_row)
    counts = {"matmul_runs": len(matmuls), "model_runs": len(models),
              "matmul_launches": sum(row["trace"]["launches_enqueued"] for row in matmuls),
              "model_launches": sum(stage["dispatch"]["launches_enqueued"]
                  for row in models for stage in row["record"]["trace"]["native"])}
    counts["total_launches"] = counts["matmul_launches"] + counts["model_launches"]
    records.same(counts, {"matmul_runs": 6, "model_runs": 10, "matmul_launches": 6,
                         "model_launches": 30, "total_launches": 36}, "framework native launch totals differ")
    adapter.close()
    require(not session.pending_operations(), "native owners remain after framework execution")
    close = session.close()
    state.session_closed = close.complete
    check.successful(close)
    for tensor, observed in retained_outputs:
        current = tensor_observation(torch, tensor, shape=observed["shape"], strides=observed["strides"],
                                     dtype=torch.float32)
        records.same(current, observed, "framework result changed after native session close")
    check.timeout_ns(deadline)
    base = {"schema_version": 1, "contract_id": "p05-installed-observations-v1",
            "scope": "simx-installed-python", "binding": dict(binding), "installation": installation,
            "matmuls": matmuls, "models": models, "counts": counts,
            "outcome": "pass", "acceptance_claimed": False}
    return {"schema_version": 1, "contract_id": "p05-torch-observations-v1",
            "scope": "simx-installed-pytorch", "outcome": "pass", "acceptance_claimed": False,
            "framework": framework, "base_observations": base,
            "framework_matmuls": framework_matmuls, "framework_models": framework_models}


_RETAINED_FAILURES = []


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args(argv)
    state = check.RunState()
    state.adapter = None
    try:
        request = records.read_request(Path(args.request), base_validator=check.validate_request)
        inspect_contract(Path(args.contract), request)
        output = Path(args.output)
        require(output.is_absolute() and output.parent.resolve(strict=True) == output.parent
                and output.parent.is_dir() and not os.path.lexists(output),
                "framework observation output must be new, absolute and canonical")
        api = importlib.import_module("vortex_ai")
        torch = importlib.import_module("torch")
        adapter = importlib.import_module("vortex_ai.torch_ops")
        installation = check.inspect_installation(request["base_request"], api)
        framework = inspect_framework(request, installation, torch, adapter)
        observations = run_matrix(request, api, torch, adapter, installation, framework, state)
        check.write_observations(output, observations)
        return 0
    except BaseException as error:
        traceback.print_exception(error, file=sys.stderr)
        sys.stderr.flush()
        check.retain_failure(state, error)
        complete = check.cleanup_failure(state)
        if state.adapter is not None:
            try:
                state.adapter.close()
            except BaseException as close_error:
                complete = False
                check.emit("P05_CLEANUP_ERROR", {"action": "framework_adapter.close", "error": str(close_error)},
                           stream=sys.stderr)
        check.emit("P05_FAILURE", {"scope": "simx-installed-pytorch", "error_type": type(error).__name__,
                                  "error": str(error), "cleanup_complete": complete}, stream=sys.stderr)
        if not complete:
            _RETAINED_FAILURES.append((state, error))
        return 2


if __name__ == "__main__":
    result = main()
    if _RETAINED_FAILURES:
        check.emit("P05_FAILURE", {"error": "native cleanup remains incomplete; terminating failed checker",
                                   "cleanup_complete": False}, stream=sys.stderr)
        sys.stdout.flush()
        sys.stderr.flush()
        try:
            import ctypes
            flush = ctypes.CDLL(None).fflush
            flush.argtypes = [ctypes.c_void_p]
            flush.restype = ctypes.c_int
            flush(None)
        except BaseException:
            pass
        os._exit(2)
    raise SystemExit(result)
