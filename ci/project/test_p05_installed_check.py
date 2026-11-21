# SPDX-License-Identifier: Apache-2.0
"""Host mocks test checker plumbing and immutable pins; no accelerator executes."""

import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

import p05_installed_check as check
from p05_qualification_test_fixture import (
    FIXTURES, MODEL_DOCUMENT, MODEL_INDEX, P02_INDEX, SOURCE,
    MockNativeError, MockOperation, MockRuntime, ModelStatus, Status, dispatch,
    installation, make_request, synthetic,
)
import p05_execution_records as records


@contextlib.contextmanager
def installed_environment(request):
    identity = installation(request)
    package = Path(identity["package_file"]).parent
    extension = package / ("_native" + check.importlib.machinery.EXTENSION_SUFFIXES[0])
    extension.write_bytes(b"HOST MOCK EXTENSION IDENTITY; NEVER LOADED\n")
    native = types.ModuleType("vortex_ai._native")
    native.__file__ = str(extension)
    native.__spec__ = types.SimpleNamespace(loader=check.importlib.machinery.ExtensionFileLoader(
        native.__name__, str(extension)))
    native.build_info = lambda: dict(identity["build_info"])
    api = types.ModuleType("vortex_ai")
    api.__file__, api.__version__, api.BINDING_API = identity["package_file"], "0.1.0", 1
    api.build_info = lambda: dict(identity["build_info"])
    api.fixture_cases = lambda: tuple(MODEL_INDEX)
    distribution = types.SimpleNamespace(version="0.1.0", locate_file=lambda name: package.parent / name)
    env = {"LD_LIBRARY_PATH": str(Path(request["binding"]["bundle_root"]) / "lib"), "VORTEX_DRIVER": "simx"}
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.dict(sys.modules))
        for name in tuple(sys.modules):
            if name == "vortex_ai" or name.startswith("vortex_ai."):
                del sys.modules[name]
        sys.modules.update({"vortex_ai": api, "vortex_ai._native": native})
        for target, attribute, replacement in (
                (sys, "flags", types.SimpleNamespace(isolated=1, ignore_environment=1, no_user_site=1)),
                (sys, "version_info", (3, 12, 14)), (sys, "prefix", request["expected_prefix"]),
                (sys, "base_prefix", "/host-mock-python"), (sys, "executable", identity["executable"])):
            stack.enter_context(patch.object(target, attribute, replacement))
        stack.enter_context(patch.object(check.platform, "python_implementation", return_value="CPython"))
        stack.enter_context(patch.object(check.importlib, "import_module", return_value=native))
        stack.enter_context(patch.object(check.importlib.metadata, "distribution", return_value=distribution))
        stack.enter_context(patch.dict(check.os.environ, env, clear=True))
        yield api, native, identity, distribution


class InstalledCheckerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="p05-checker-host-mock-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.request = self.make_request("fp16")

    def make_request(self, fmt):
        return make_request(self.root, fmt)

    def test_all_fixture_pins_reproduce(self):
        self.assertEqual(set(check.MATMUL_SHA256), {fmt + "-" + family for fmt in ("fp16", "bf16")
            for family in ("single-dense_boundaries", "numerical-cross_tile_rounding_positive", "multi-dense_boundaries")})
        self.assertEqual(set(check.MODEL_OUTPUT_SHA256), {case["family"] for case in MODEL_DOCUMENT["cases"]})
        for name, expected in check.MATMUL_SHA256.items():
            self.assertEqual(hashlib.sha256(check.canonical(P02_INDEX[name])).hexdigest(), expected)
        for case in MODEL_DOCUMENT["cases"]:
            expected = check.MODEL_OUTPUT_SHA256[case["family"]]
            self.assertEqual(hashlib.sha256(check.packed(case["output_words"])).hexdigest(), expected)
        self.assertEqual(hashlib.sha256((FIXTURES / "p04_tiny_mlp_v1.json").read_bytes()).hexdigest(), check.MODEL_FIXTURE_SHA256)

    def test_both_complete_mock_matrices(self):
        for fmt in ("fp16", "bf16"):
            request = self.make_request(fmt)
            check.validate_request(request)
            state, runtime, captured = check.RunState(), MockRuntime(request), io.StringIO()
            with contextlib.redirect_stdout(captured):
                value = check.run_matrix(request, runtime.api, installation(request), state)
            rows = captured.getvalue().splitlines()
            self.assertEqual([json.loads(row[11:]) for row in rows if row.startswith("P05_MATMUL ")], value["matmuls"])
            self.assertEqual([json.loads(row[10:]) for row in rows if row.startswith("P05_MODEL ")], value["models"])
            self.assertEqual(value["counts"], {"matmul_runs": 6, "model_runs": 10, "matmul_launches": 6,
                                              "model_launches": 30, "total_launches": 36})
            self.assertEqual(set(value), {"schema_version", "contract_id", "scope", "binding", "installation",
                                          "matmuls", "models", "counts", "outcome", "acceptance_claimed"})
            self.assertEqual(runtime.close_count, 16)
            self.assertEqual(runtime.max_contexts, 1)
            self.assertTrue(runtime.session_closed and state.session_closed)
            self.assertFalse(runtime.pending)
            self.assertTrue(all(0 < timeout <= 1000000000 for timeout in runtime.timeouts))
            self.assertFalse(value["acceptance_claimed"])
            _, _, native = synthetic(self.root, fmt)
            compared = records.verify_observations(value, request, raw_log=captured.getvalue(), **native)
            self.assertEqual(compared["counts"], value["counts"])
            self.assertEqual(compared["event_profile_pairs"], 180)

    def test_frozen_request_rejects_corruption(self):
        for mutate in (lambda value: value["matmul_cases"][0]["a_words"].__setitem__(0, "00000000"),
                       lambda value: value["matmul_cases"].reverse(),
                       lambda value: value["model_cases"].reverse(),
                       lambda value: value.update(iterations=True),
                       lambda value: value["binding"].update(qualification_id="bad"),
                       lambda value: value.update(extra=True)):
            value = copy.deepcopy(self.request)
            mutate(value)
            with self.assertRaises(check.CheckError):
                check.validate_request(value)

    def test_json_duplicate_float_symlink_and_oversize_rejection(self):
        path = self.root / "request.json"
        for payload in (b'{"x":1,"x":2}', b'{"x":1.0}', b'{"x":NaN}', b'x'*(check.MAX_REQUEST_BYTES+1)):
            path.write_bytes(payload)
            with self.assertRaises(check.CheckError):
                check.read_request(path)
        path.write_bytes(check.canonical(self.request))
        link = self.root / "alias.json"
        link.symlink_to(path)
        with self.assertRaises(check.CheckError):
            check.read_request(link)
        self.assertEqual(check.read_request(path), self.request)

    def test_wrong_output_retains_actual_raw_row(self):
        state, runtime, captured = check.RunState(), MockRuntime(self.request), io.StringIO()
        runtime.corrupt_output = True
        with contextlib.redirect_stdout(captured), self.assertRaisesRegex(check.CheckError, "immutable fixture"):
            check.run_matrix(self.request, runtime.api, {}, state)
        raw = json.loads(captured.getvalue().splitlines()[0][11:])
        self.assertNotEqual(raw["actual_bits"], self.request["matmul_cases"][0]["expected"])
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertTrue(check.cleanup_failure(state))
        self.assertEqual(runtime.close_count, 1)

    def test_native_error_remains_primary_after_explicit_cleanup(self):
        state, runtime = check.RunState(), MockRuntime(self.request)
        runtime.native_error = True
        with self.assertRaises(MockNativeError) as caught:
            check.run_matrix(self.request, runtime.api, {}, state)
        original = caught.exception
        self.assertEqual(original.status.primary, 6)
        with contextlib.redirect_stderr(io.StringIO()):
            check.retain_failure(state, original)
            self.assertTrue(check.cleanup_failure(state))
        self.assertEqual(original.status.primary, 6)
        self.assertTrue(runtime.session_closed)
        self.assertEqual(runtime.close_count, 1)

    def test_deadline_cleanup_retains_pending_owner(self):
        state, runtime = check.RunState(), MockRuntime(self.request)
        runtime.open(self.request["binding"]["bundle_root"])
        state.session = runtime
        owner = MockOperation(runtime, self.request["matmul_cases"][0], check.POISONS[0], 10000)
        runtime.pending.append(owner)
        state.retain(owner)
        runtime.never_closes = True
        with self.assertRaises(TimeoutError):
            check.wait_matmul(owner, time.monotonic() - 1)
        with patch.object(check, "CLEANUP_SECONDS", 0.03), contextlib.redirect_stderr(io.StringIO()):
            self.assertFalse(check.cleanup_failure(state))
        self.assertIs(state.owners[0], owner)
        self.assertFalse(state.session_closed)
        runtime.never_closes = False
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertTrue(check.cleanup_failure(state))

    def test_final_file_published_only_after_success(self):
        request_path = self.root / "request.json"
        request_path.write_bytes(check.canonical(self.request))
        output_path = self.root / "observations.json"
        runtime = MockRuntime(self.request)
        with patch.object(check.importlib, "import_module", return_value=runtime.api), \
             patch.object(check, "inspect_installation", return_value={}), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(check.main(["--request", str(request_path), "--output", str(output_path)]), 0)
        self.assertTrue(runtime.session_closed)
        self.assertEqual(json.loads(output_path.read_bytes())["counts"]["total_launches"], 36)
        original = output_path.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(check.main(["--request", str(request_path), "--output", str(output_path)]), 2)
        self.assertEqual(output_path.read_bytes(), original)
        output_path.unlink()
        runtime = MockRuntime(self.request)
        runtime.corrupt_output = True
        with patch.object(check.importlib, "import_module", return_value=runtime.api), \
             patch.object(check, "inspect_installation", return_value={}), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(check.main(["--request", str(request_path), "--output", str(output_path)]), 2)
        self.assertFalse(output_path.exists())
        self.assertTrue(runtime.session_closed)

    def test_installation_identity_paths_loader_and_pins(self):
        with installed_environment(self.request) as (api, native, identity, _):
            self.assertEqual(check.inspect_installation(self.request, api)["extension_file"], native.__file__)
            identity["build_info"]["bundle_sha256"] = "f" * 64
            with self.assertRaisesRegex(check.CheckError, "pins"):
                check.inspect_installation(self.request, api)
            identity["build_info"]["bundle_sha256"] = "a" * 64
            loader = native.__spec__.loader
            native.__spec__.loader = object()
            with self.assertRaisesRegex(check.CheckError, "compiled extension"):
                check.inspect_installation(self.request, api)
            native.__spec__.loader = loader
            native.__file__ = str(SOURCE / "python/vortex_ai/__init__.py")
            with self.assertRaisesRegex(check.CheckError, "outside the isolated venv"):
                check.inspect_installation(self.request, api)

    def test_copied_checker_cannot_import_source_in_clean_venv(self):
        prefix = self.root / "clean-venv"
        made = subprocess.run([sys.executable, "-I", "-m", "venv", "--copies", "--without-pip", str(prefix)],
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(made.returncode, 0, made.stderr)
        copied = self.root / "outside-checkout.py"
        shutil.copyfile(SOURCE / "ci/project/p05_installed_check.py", copied)
        self.request["expected_prefix"] = str(prefix)
        request_path, output_path = self.root / "request.json", self.root / "observations.json"
        request_path.write_bytes(check.canonical(self.request))
        result = subprocess.run([str(prefix / "bin/python"), "-I", "-B", str(copied),
                                 "--request", str(request_path), "--output", str(output_path)],
                                cwd=self.root, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertIn("No module named 'vortex_ai'", result.stderr)
        self.assertFalse(output_path.exists())

    def test_main_retains_incomplete_owners_without_exiting_caller(self):
        request_path, output_path = self.root / "request.json", self.root / "observations.json"
        request_path.write_bytes(check.canonical(self.request))
        runtime = MockRuntime(self.request)
        runtime.never_closes = True
        with patch.object(check.importlib, "import_module", return_value=runtime.api), \
             patch.object(check, "inspect_installation", return_value={}), \
             patch.object(check, "MATRIX_SECONDS", 0.03), patch.object(check, "CLEANUP_SECONDS", 0.03), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(check.main(["--request", str(request_path), "--output", str(output_path)]), 2)
        self.assertFalse(output_path.exists())
        state, error = check._RETAINED_FAILURES.pop()
        self.assertIsInstance(error, TimeoutError)
        self.assertIs(state.owners[0], runtime.pending[0])
        runtime.never_closes = False
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertTrue(check.cleanup_failure(state))

    def test_abi_profiles_and_resource_corruption_fail(self):
        case = self.request["matmul_cases"][0]
        shape = tuple(case[key] for key in ("m", "n", "k"))
        valid = dispatch(shape, "fp16", check.POISONS[0], "c"*64, 10000)
        for mutate in (lambda row: row.update(argument_bytes="00"*56),
                       lambda row: row.update(launches_enqueued=0),
                       lambda row: row["event_profile_queried"].__setitem__(1, False),
                       lambda row: row["event_results"].__setitem__(0, True),
                       lambda row: row["event_profiles"][1].update(end_ns=0)):
            value = copy.deepcopy(valid)
            mutate(value)
            with self.assertRaises(check.CheckError):
                check.dispatch(value, shape, "fp16", check.POISONS[0], "c"*64)
        runtime = MockRuntime(self.request)
        owner = MockOperation(runtime, MODEL_INDEX["fp16-zero"], check.POISONS[0], 10000, True)
        owner.closed = True
        owner.result["trace"]["resources"]["used_after"] += 1
        with self.assertRaisesRegex(check.CheckError, "resources"):
            check.check_model(owner.record(0), owner, "fp16-zero", 0, self.request["binding"])

    def test_request_contract_inventory_identity_and_canonical_paths(self):
        for label, mutate in (
                ("schema", lambda value: value.update(schema_version=True)),
                ("iteration", lambda value: value.update(iterations=1)),
                ("backend", lambda value: value["binding"].update(backend="rtlsim")),
                ("format", lambda value: value["binding"].update(format="fp32")),
                ("source hash", lambda value: value["binding"].update(source_sha256="A" * 64)),
                ("revision", lambda value: value["binding"].update(source_revision="d" * 39)),
                ("binding extra", lambda value: value["binding"].update(unexpected=True)),
                ("matmul missing", lambda value: value["matmul_cases"].pop()),
                ("model missing", lambda value: value["model_cases"].pop()),
                ("relative prefix", lambda value: value.update(expected_prefix="venv")),
                ("bundle parent", lambda value: value["binding"].update(bundle_root=str(self.root / "venv/../bundle")))):
            value = copy.deepcopy(self.request)
            mutate(value)
            with self.subTest(label=label), self.assertRaises(check.CheckError):
                check.validate_request(value)
        alias = self.root / "bundle-alias"
        alias.symlink_to(self.root / "bundle", target_is_directory=True)
        value = copy.deepcopy(self.request)
        value["binding"]["bundle_root"] = str(alias)
        with self.assertRaisesRegex(check.CheckError, "canonical"):
            check.validate_request(value)

    def test_request_integer_depth_encoding_and_file_bounds(self):
        path = self.root / "request.json"
        for payload in (b'{"x":' + b"9" * 65 + b'}', b"[" * 2000, b"\xff", b'{"x":Infinity}'):
            path.write_bytes(payload)
            with self.subTest(payload=repr(payload[:30])), self.assertRaises(check.CheckError):
                check.read_request(path)
        with self.assertRaisesRegex(check.CheckError, "regular file"):
            check.read_request(self.root)

    def test_raw_words_preserve_signed_zero_nan_and_payload_bits(self):
        words = ["00000000", "80000000", "7fc0dead", "deadbeef", "00000001", "7f800000"]
        self.assertEqual(check.output_words(check.packed(words), len(words)), words)
        for value in (bytearray(4), memoryview(bytes(4)), b"", bytes(3), bytes(8)):
            with self.subTest(type=type(value).__name__, size=len(value)), self.assertRaises(check.CheckError):
                check.output_words(value, 1)

    def test_execution_status_requires_dataclass_exact_types_and_success(self):
        for status in (Status, {}, types.SimpleNamespace(), Status(primary=True), Status(cleanup=-1),
                       Status(validation=0), Status(complete=1)):
            with self.subTest(status=repr(status)), self.assertRaises(check.CheckError):
                check.execution(status)
        operation = object()
        status = Status(primary=6, cleanup=10)
        with self.assertRaises(MockNativeError) as caught:
            check.successful(status, operation)
        self.assertIs(caught.exception.operation, operation)
        self.assertEqual((caught.exception.status.primary, caught.exception.status.cleanup), (6, 10))

    def test_memory_info_requires_observed_successful_integer_tuple(self):
        for value in ([0, 1, 2], (0, 1), (6, 1, 2), (False, 1, 2), (0, -1, 2), (0, 1, 1 << 64)):
            session = types.SimpleNamespace(memory_info=lambda: value)
            with self.subTest(value=value), self.assertRaises(check.CheckError):
                check.memory_info(session)

    def test_wait_deadlines_are_positive_bounded_and_do_not_call_after_expiry(self):
        with patch.object(check.time, "monotonic", return_value=10):
            self.assertEqual(check.timeout_ns(20), check.WAIT_NS)
            self.assertEqual(check.timeout_ns(10.0000000001), 1)
            for deadline in (10, 9):
                with self.assertRaises(TimeoutError):
                    check.timeout_ns(deadline)
            wait = unittest.mock.Mock()
            operation = types.SimpleNamespace(status=Status(complete=False), wait=wait)
            with self.assertRaises(TimeoutError):
                check.wait_matmul(operation, 9)
            wait.assert_not_called()
            operation.status = ModelStatus()
            operation.advance = wait
            with self.assertRaises(TimeoutError):
                check.advance_model(operation, 9)
            wait.assert_not_called()

    def test_terminal_errors_preserve_owner_before_any_more_waits(self):
        wait = unittest.mock.Mock()
        status = Status(primary=6, cleanup=10, complete=True)
        operation = types.SimpleNamespace(status=status, wait=wait)
        with self.assertRaises(MockNativeError) as caught:
            check.wait_matmul(operation, time.monotonic() + 1)
        self.assertIs(caught.exception.operation, operation)
        self.assertIs(caught.exception.status, status)
        wait.assert_not_called()
        operation.status = ModelStatus("execution_failure", status, True)
        operation.advance = wait
        with self.assertRaises(MockNativeError) as caught:
            check.advance_model(operation, time.monotonic() + 1)
        self.assertIs(caught.exception.operation, operation)
        self.assertIs(caught.exception.status, status)
        wait.assert_not_called()

    def test_retain_failure_recovers_exception_session_and_deduplicates_owner(self):
        state, runtime = check.RunState(), MockRuntime(self.request)
        runtime.open(self.request["binding"]["bundle_root"])
        owner = MockOperation(runtime, self.request["matmul_cases"][0], check.POISONS[0], 10000)
        runtime.pending.append(owner)
        error = MockNativeError(Status(primary=6, complete=False), owner)
        error.session = runtime
        check.retain_failure(state, error)
        check.retain_failure(state, error)
        self.assertIs(state.session, runtime)
        self.assertEqual(len(state.owners), 1)
        self.assertIs(state.owners[0], owner)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertTrue(check.cleanup_failure(state))
        self.assertEqual(error.status.primary, 6)

    def test_cleanup_keeps_primary_error_and_reports_trace_failure(self):
        state, runtime = check.RunState(), MockRuntime(self.request)
        runtime.open(self.request["binding"]["bundle_root"])
        state.session = runtime
        owner = MockOperation(runtime, self.request["matmul_cases"][0], check.POISONS[0], 10000)
        runtime.pending.append(owner)
        state.retain(owner)
        original = MockNativeError(Status(primary=6, cleanup=10, complete=False), owner)
        diagnostic = io.StringIO()
        with patch.object(owner, "trace", side_effect=MemoryError("host mock diagnostic failure")), \
             contextlib.redirect_stderr(diagnostic):
            self.assertTrue(check.cleanup_failure(state))
        rows = diagnostic.getvalue().splitlines()
        errors = [json.loads(row[len("P05_CLEANUP_ERROR "):]) for row in rows if row.startswith("P05_CLEANUP_ERROR ")]
        self.assertEqual(errors, [{"action": "trace", "error": "host mock diagnostic failure"}])
        self.assertEqual((original.status.primary, original.status.cleanup), (6, 10))
        self.assertIs(original.operation, owner)
        self.assertIn(id(owner), state.closed)

    def test_pending_inventory_failure_is_diagnostic_and_keeps_exception_owner(self):
        owner = object()
        error = MockNativeError(Status(primary=6, complete=False), owner)
        error.session = types.SimpleNamespace(pending_operations=unittest.mock.Mock(
            side_effect=RuntimeError("host mock pending observation failure")))
        state, output = check.RunState(), io.StringIO()
        with contextlib.redirect_stderr(output):
            check.retain_failure(state, error)
        self.assertEqual(state.owners, [owner])
        self.assertIs(state.session, error.session)
        diagnostic = json.loads(output.getvalue().removeprefix("P05_CLEANUP_ERROR "))
        self.assertEqual(diagnostic["action"], "pending_operations")
        self.assertIn("host mock pending", diagnostic["error"])

    def test_model_failure_raw_record_is_retained_before_validation(self):
        state, runtime, captured = check.RunState(), MockRuntime(self.request), io.StringIO()
        submit = runtime.model
        def corrupt(case_id, poison):
            owner = submit(case_id, poison)
            owner.result["trace"]["owner_closed"] = False
            return owner
        with patch.object(runtime, "model", side_effect=corrupt), contextlib.redirect_stdout(captured), \
             self.assertRaisesRegex(check.CheckError, "owner_closed"):
            check.run_matrix(self.request, runtime.api, {}, state)
        lines = captured.getvalue().splitlines()
        self.assertEqual(sum(line.startswith("P05_MATMUL ") for line in lines), 6)
        self.assertEqual(sum(line.startswith("P05_MODEL ") for line in lines), 1)
        row = json.loads(lines[-1][len("P05_MODEL "):])
        self.assertFalse(row["record"]["trace"]["owner_closed"])
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertTrue(check.cleanup_failure(state))

    def test_model_status_and_record_identity_require_successful_explicit_close(self):
        runtime = MockRuntime(self.request)
        owner = MockOperation(runtime, MODEL_INDEX["fp16-zero"], check.POISONS[0], 10000, True)
        owner.closed = True
        original = copy.deepcopy(owner.result)
        for label, mutate in (
                ("source", lambda row: row.update(source_revision="f" * 40)),
                ("fixture", lambda row: row.update(fixture_sha256="f" * 64)),
                ("iteration", lambda row: row.update(iteration=True)),
                ("poison", lambda row: row["trace"].update(poison=check.POISONS[1])),
                ("owner", lambda row: row["trace"].update(owner_closed=False)),
                ("terminal", lambda row: row["trace"]["result"].update(terminal=False)),
                ("cleanup", lambda row: row["trace"]["owner_cleanup"].update(cleanup=6)),
                ("bridge bytes", lambda row: row["trace"].update(bridge_bytes="ff" * 256)),
                ("stage order", lambda row: row["trace"]["native"].reverse())):
            owner.result = copy.deepcopy(original)
            mutate(owner.result)
            with self.subTest(label=label), self.assertRaises(check.CheckError):
                check.check_model(owner.result, owner, "fp16-zero", 0, self.request["binding"])

    def test_session_identity_requires_exact_binding_library_order_and_regular_files(self):
        original = MockRuntime(self.request)
        self.assertEqual(check.session_identity(original, self.request), list(original.info["libraries"]))
        for key, replacement in (("format", "bf16"), ("backend", "rtlsim"),
                                  ("qualification_id", "f" * 64), ("source_revision", "f" * 40),
                                  ("libraries", tuple(reversed(original.info["libraries"])))):
            runtime = MockRuntime(self.request)
            runtime.info[key] = replacement
            with self.subTest(field=key), self.assertRaises(check.CheckError):
                check.session_identity(runtime, self.request)
        library = Path(original.info["libraries"][0])
        target = library.with_suffix(".target")
        library.rename(target)
        library.symlink_to(target)
        with self.assertRaisesRegex(check.CheckError, "symlinks"):
            check.session_identity(original, self.request)

    def test_inspection_rejects_nonisolated_interpreter_and_loader_overrides(self):
        with installed_environment(self.request) as (api, _, _, _):
            self.assertEqual(check.inspect_installation(self.request, api)["prefix"], self.request["expected_prefix"])
            for name in ("isolated", "ignore_environment", "no_user_site"):
                flags = types.SimpleNamespace(isolated=1, ignore_environment=1, no_user_site=1)
                setattr(flags, name, 0)
                with self.subTest(flag=name), patch.object(sys, "flags", flags), \
                     self.assertRaisesRegex(check.CheckError, "python -I"):
                    check.inspect_installation(self.request, api)
            for key, value in (("LD_LIBRARY_PATH", "/foreign/lib"), ("LD_AUDIT", "/foreign/audit.so"),
                               ("LD_PRELOAD", "/foreign/preload.so"), ("VORTEX_DRIVER", "rtlsim")):
                with self.subTest(environment=key), patch.dict(check.os.environ, {key: value}), \
                     self.assertRaisesRegex(check.CheckError, "loader environment"):
                    check.inspect_installation(self.request, api)

    def test_inspection_rejects_foreign_loaded_submodule_and_distribution(self):
        with installed_environment(self.request) as (api, _, _, distribution):
            foreign = types.ModuleType("vortex_ai.foreign")
            foreign.__file__ = str(SOURCE / "python/vortex_ai/__init__.py")
            with patch.dict(sys.modules, {foreign.__name__: foreign}), \
                 self.assertRaisesRegex(check.CheckError, "outside the installed package"):
                check.inspect_installation(self.request, api)
            distribution.version = "9.9.9"
            with self.assertRaisesRegex(check.CheckError, "distribution identity"):
                check.inspect_installation(self.request, api)
            distribution.version = "0.1.0"
            api.BINDING_API = True
            with self.assertRaisesRegex(check.CheckError, "binding API"):
                check.inspect_installation(self.request, api)

    def test_output_publication_is_exclusive_and_cleans_temporary_file_on_failure(self):
        destination = self.root / "observations.json"
        check.write_observations(destination, {"value": 1})
        original = destination.read_bytes()
        with self.assertRaises(FileExistsError):
            check.write_observations(destination, {"value": 2})
        self.assertEqual(destination.read_bytes(), original)
        destination.unlink()
        with patch.object(check.os, "link", side_effect=OSError("host mock link failure")), self.assertRaises(OSError):
            check.write_observations(destination, {"value": 3})
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob(".p05-observations-*")), [])



if __name__ == "__main__":
    unittest.main(verbosity=2)
