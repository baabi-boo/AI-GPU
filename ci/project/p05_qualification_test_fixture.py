# SPDX-License-Identifier: Apache-2.0
"""Synthetic host-only qualification fixtures; never accelerator execution evidence."""

import copy
from dataclasses import dataclass
import json
from pathlib import Path
import struct
import types

import p05_installed_check as check


SOURCE = Path(__file__).resolve().parents[2]
FIXTURES = SOURCE / "ci/project/fixtures"
P02 = [dict(row, **row["dimensions"]) for filename in ("p02_layout_v1.json", "p02_wmma_numerical_v1.json")
       for row in json.loads((FIXTURES / filename).read_text())["cases"]]
P02_INDEX = {row["id"]: row for row in P02}
MODEL_DOCUMENT = json.loads((FIXTURES / "p04_tiny_mlp_v1.json").read_text())
MODEL_INDEX = {row["id"]: {**row, **MODEL_DOCUMENT["weights"]["formats"][row["format"]]}
               for row in MODEL_DOCUMENT["cases"]}


class MockNativeError(RuntimeError):
    def __init__(self, status, operation=None):
        super().__init__("host mock native failure " + repr(status))
        self.status = status
        self.operation = operation


@dataclass(frozen=True)
class Status:
    validation: str = "success"
    primary: int = 0
    cleanup: int = 0
    complete: bool = True

    @property
    def ok(self):
        return self == Status()

    def raise_for_status(self, operation=None):
        if not self.ok:
            raise MockNativeError(self, operation)


@dataclass(frozen=True)
class ModelStatus:
    status: str = "in_progress"
    execution: Status = Status()
    terminal: bool = False

    def raise_for_status(self, operation=None):
        if not (self.status == "success" and self.terminal and self.execution.ok):
            raise MockNativeError(self.execution, operation)


@dataclass(frozen=True)
class Tensor:
    data: bytes
    dtype: str
    shape: tuple
    layout: str


def nstatus(complete=True):
    return {"validation": 0, "primary": 0, "cleanup": 0, "complete": complete}


def dispatch(shape, fmt, poison, binding, epoch):
    m, n, k = shape
    value = {"qualification_id": binding, "input_dtype": fmt, "m": m, "n": n, "k": k,
             "poison": poison, "a_address": 0x1000, "b_address": 0x2000, "d_address": 0x3000,
             "a_bytes": m * k * 2, "b_bytes": k * n * 2, "d_bytes": m * n * 4,
             "writes_enqueued": 3, "launches_enqueued": 1, "reads_enqueued": 1,
             "wait_calls": 2, "timed_out_waits": 1, "event_results": [0] * 5,
             "profiling_enabled": True, "event_profile_results": [0] * 5,
             "event_profile_queried": [True] * 5,
             "event_profiles": [{"queued_ns": epoch + event, "submit_ns": epoch + 20 + event * 10,
                                 "start_ns": epoch + 22 + event * 10, "end_ns": epoch + 25 + event * 10}
                                for event in range(5)]}
    value["argument_bytes"] = struct.pack("<8I3Q", 1, 56, 1 if fmt == "fp16" else 2, 0,
                                           m, n, k, 0, 0x1000, 0x2000, 0x3000).hex()
    return value


def model_record(case, iteration, binding, epoch):
    poison = check.POISONS[iteration]
    trace = {"case_id": case["id"], "input_dtype": case["format"], "poison": poison,
             "native": [], "hidden_valid": True, "bridge_attempted": True,
             "bridge_valid": True, "bridge_compared": True, "assembled": True,
             "logits_valid": True, "logits_compared": True, "owner_closed": True,
             "bridge_status": 0, "hidden_words": list(case["hidden_words"]),
             "bridge_bytes": check.packed(case["bridge_words"]).hex(), "bridge_words": list(case["bridge_words"]),
             "output_words": list(case["output_words"]), "bridge_checked_words": 64,
             "bridge_mismatches": 0, "output_checked_words": 64, "output_mismatches": 0,
             "create_begin_ns": epoch + 100, "create_end_ns": epoch + 200, "advance_ns": 4000,
             "bridge_ns": 5, "bridge_compare_ns": 5, "assembly_ns": 5,
             "output_compare_ns": 5, "close_ns": 10,
             "resources": {"before_valid": True, "after_valid": True, "before_status": 0,
                           "after_status": 0, "free_before": 0x100000, "used_before": 0x20000,
                           "free_after": 0x100000, "used_after": 0x20000},
             "owner_cleanup": nstatus(),
             "result": {"status": "success", "execution": nstatus(), "terminal": True}}
    for index, (name, shape, rows) in enumerate((("hidden_matmul", (16, 8, 16), (0, 16)),
                                                ("output_rows_0_7", (8, 4, 8), (0, 8)),
                                                ("output_rows_8_15", (8, 4, 8), (8, 16)))):
        m, n, k = shape
        begin = epoch + 1000 + index * 1000
        a = check.packed(case["input_words"]).hex() if not index else trace["bridge_bytes"][(index-1)*256:index*256]
        b = check.packed(case["w1_words"] if not index else case["w2_words"]).hex()
        output = case["hidden_words"] if not index else case["output_words"][(index-1)*32:index*32]
        trace["native"].append({"operation_id": name, "sequence": index,
            "row_begin": rows[0], "row_end": rows[1], "submitted": True, "waited": True,
            "trace_valid": True, "output_valid": True, "compared": True, "closed": True,
            "submission": nstatus(False), "completion": nstatus(), "cleanup": nstatus(),
            "dispatch": dispatch(shape, case["format"], poison, binding["qualification_id"], begin),
            "a_size": m*k*2, "b_size": k*n*2, "output_count": m*n, "a_bytes": a,
            "b_bytes": b, "output_words": list(output), "checked_words": m*n, "mismatches": 0,
            "submit_begin_ns": begin, "submit_end_ns": begin+10, "wait_ns": 100,
            "compare_ns": 5, "close_ns": 5})
    return {"schema_version": 1, "model_id": "p04-tiny-mlp-v1",
            "fixture_id": "p04-tiny-mlp-fixture-v1", "fixture_sha256": check.MODEL_FIXTURE_SHA256,
            "source_revision": binding["source_revision"], "backend": "simx", "iteration": iteration,
            "qualification_id": binding["qualification_id"], "clock": "std::chrono::steady_clock",
            "timing_scope": "host_runtime_observations", "trace": trace}


class MockOperation:
    def __init__(self, runtime, case, poison, epoch, is_model=False):
        self.runtime, self.case, self.poison, self.epoch = runtime, case, poison, epoch
        self.is_model = is_model
        self.status = ModelStatus() if is_model else Status(complete=False)
        self.waits = self.closes = 0
        self.closed = False
        if is_model:
            self.result = model_record(case, check.POISONS.index(poison), runtime.request["binding"], epoch)
        else:
            self.result = dispatch(tuple(case[k] for k in ("m", "n", "k")), case["format"], poison,
                                   runtime.request["binding"]["qualification_id"], epoch)

    def wait(self, timeout_ns):
        self.runtime.timeouts.append(timeout_ns)
        self.waits += 1
        self.status = Status(primary=7, complete=False) if self.waits == 1 else Status()
        if self.runtime.native_error and self.waits > 1:
            self.status = Status(primary=6, complete=False)
        return self.status

    def advance(self, timeout_ns):
        result = self.wait(timeout_ns)
        self.status = ModelStatus("success" if result.ok else "in_progress", result, result.ok)
        return self.status

    def close(self, timeout_ns):
        self.runtime.timeouts.append(timeout_ns)
        self.closes += 1
        if self.runtime.never_closes or self.closes == 1:
            return Status(primary=7, complete=False)
        self.closed = True
        self.runtime.pending.remove(self)
        self.runtime.close_count += 1
        if self.is_model:
            self.runtime.contexts -= 1
        result = Status(primary=6 if self.runtime.native_error else 0)
        if not self.is_model:
            self.status = result
        return result

    def output_bytes(self):
        assert self.closed, "outputs inspected before explicit close"
        source = self.case["output_words"] if self.is_model else self.case["expected"]
        data = check.packed(source)
        return bytes([data[0] ^ 1]) + data[1:] if self.runtime.corrupt_output else data

    def trace(self):
        return copy.deepcopy(self.result["trace"] if self.is_model else self.result)

    def record(self, iteration):
        assert self.closed, "native model record inspected before explicit close"
        assert self.result["iteration"] == iteration
        return copy.deepcopy(self.result)


class MockRuntime:
    def __init__(self, request):
        self.request = request
        self.pending, self.timeouts = [], []
        self.epoch = self.close_count = self.max_contexts = self.contexts = 0
        self.session_closed = self.native_error = self.never_closes = self.corrupt_output = False
        self.tensor_bytes = []
        self.status = Status()
        binding = request["binding"]
        self.info = {key: value for key, value in binding.items() if key != "bundle_root"}
        self.info["libraries"] = tuple(str(Path(binding["bundle_root"]) / "lib" / name)
                                       for name in check.LIBRARY_NAMES)
        self.api = types.SimpleNamespace(Session=types.SimpleNamespace(open=self.open), Tensor=Tensor)

    def open(self, bundle):
        assert bundle == self.request["binding"]["bundle_root"]
        self.contexts = self.max_contexts = 1
        return self

    def pending_operations(self):
        return tuple(self.pending)

    def memory_info(self):
        return 0, 1000000, 200000

    def submit(self, a, b, poison):
        assert not self.pending and self.contexts == 1
        self.epoch += 10000
        case = next(case for case in self.request["matmul_cases"]
                    if (case["m"], case["k"]) == a.shape and (case["k"], case["n"]) == b.shape)
        assert a.layout == "row_major" and b.layout == "column_major"
        assert a.data == check.packed(case["a_words"]) and b.data == check.packed(case["b_words"])
        assert type(a.data) is bytes and type(b.data) is bytes
        self.tensor_bytes.append((a.data, b.data))
        owner = MockOperation(self, case, poison, self.epoch)
        self.pending.append(owner)
        return owner

    def model(self, case_id, poison):
        assert not self.pending
        self.contexts = 0
        self.contexts += 1
        self.max_contexts = max(self.max_contexts, self.contexts)
        self.epoch += 10000
        owner = MockOperation(self, MODEL_INDEX[case_id], poison, self.epoch, True)
        self.pending.append(owner)
        return owner

    def close(self):
        if self.pending:
            return Status(primary=7, complete=False)
        self.session_closed = True
        self.contexts = 0
        return Status()


def make_request(directory, fmt="fp16"):
    for name in ("bundle/lib", "venv"):
        (directory / name).mkdir(parents=True, exist_ok=True)
    for name in check.LIBRARY_NAMES:
        (directory / "bundle/lib" / name).write_bytes(b"HOST MOCK, NOT A SHARED LIBRARY\n")
    return {"schema_version": 1, "contract_id": "p05-installed-request-v1", "iterations": 2,
            "binding": {"backend": "simx", "format": fmt, "bundle_root": str(directory / "bundle"),
                        "bundle_sha256": "a" * 64, "source_sha256": "b" * 64,
                        "qualification_id": "c" * 64, "source_revision": "d" * 40},
            "matmul_cases": [copy.deepcopy(P02_INDEX[fmt + "-" + family])
                             for family, _ in check.MATMUL_SELECTION],
            "model_cases": [fmt + "-" + family for family in check.MODEL_FAMILIES],
            "expected_prefix": str(directory / "venv")}


def installation(request):
    prefix = Path(request["expected_prefix"])
    site = prefix / "lib/python3.12/site-packages/vortex_ai"
    site.mkdir(parents=True, exist_ok=True)
    (prefix / "bin").mkdir(exist_ok=True)
    paths = {"executable": prefix / "bin/python", "package_file": site / "__init__.py",
             "extension_file": site / "_native.cpython-312-x86_64-linux-gnu.so"}
    for path in paths.values():
        path.write_bytes(b"HOST MOCK IDENTITY, NEVER EXECUTED OR LOADED\n")
    binding = request["binding"]
    return {"python_version": [3, 12, 14], "python_implementation": "CPython",
            **{key: str(path) for key, path in paths.items()},
            "prefix": str(prefix), "base_prefix": "/host-mock-python",
            "distribution_version": "0.1.0", "build_info": {"binding_api": 1,
                "bundle_sha256": binding["bundle_sha256"], "source_sha256": binding["source_sha256"]},
            "runtime_libraries": [str(Path(binding["bundle_root"]) / "lib" / name)
                                  for name in check.LIBRARY_NAMES]}


def raw_log(value):
    return "".join(marker + " " + json.dumps(row, separators=(",", ":")) + "\n"
                   for marker, rows in (("P05_MATMUL", value["matmuls"]), ("P05_MODEL", value["models"]))
                   for row in rows)


def synthetic(directory, fmt="fp16"):
    import test_p03_execution_records as matmul_fixture
    request = make_request(directory, fmt)
    binding = request["binding"]
    value = {"schema_version": 1, "contract_id": "p05-installed-observations-v1",
             "scope": "simx-installed-python", "binding": copy.deepcopy(binding),
             "installation": installation(request), "matmuls": [], "models": [],
             "counts": {"matmul_runs": 6, "model_runs": 10, "matmul_launches": 6,
                        "model_launches": 30, "total_launches": 36},
             "outcome": "pass", "acceptance_claimed": False}
    native_matmuls, native_models = {}, {}
    success = {"validation": "success", "primary": 0, "cleanup": 0, "complete": True}
    for case_index, case in enumerate(request["matmul_cases"]):
        native_matmuls[case["id"]] = []
        for iteration, poison in enumerate(check.POISONS):
            native = matmul_fixture.result(case, iteration)
            native["qualification_id"] = "e" * 64
            native_matmuls[case["id"]].append(native)
            value["matmuls"].append({"case_id": case["id"], "iteration": iteration,
                "status": dict(success), "close_status": dict(success),
                "actual_bits": list(case["expected"]),
                "trace": dispatch(tuple(case[key] for key in ("m", "n", "k")), fmt, poison,
                                  binding["qualification_id"], 10000 * (1 + case_index * 2 + iteration)),
                "resources": {"before_status": 0, "after_status": 0, "free_before": 0x100000,
                              "free_after": 0x100000, "used_before": 0x20000, "used_after": 0x20000}})
    model_cases = [copy.deepcopy(MODEL_INDEX[identifier]) for identifier in request["model_cases"]]
    for case_index, case in enumerate(model_cases):
        native_models[case["id"]] = []
        for iteration in range(2):
            row = model_record(case, iteration, binding, 100000 + case_index * 20000 + iteration * 10000)
            native_models[case["id"]].append(copy.deepcopy(row))
            value["models"].append({"case_id": case["id"], "iteration": iteration, "record": row})
    return value, request, {"native_matmuls": native_matmuls, "native_models": native_models,
                            "model_cases": model_cases}
