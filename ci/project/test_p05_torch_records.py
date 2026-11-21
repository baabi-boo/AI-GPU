# SPDX-License-Identifier: Apache-2.0
"""Adversarial framework observation checks using synthetic host data only."""

import copy
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import p05_execution_records as base_records
import p05_torch_records as records
import p05_torch_installed_check as installed_check
from p05_torch_qualification_test_fixture import raw_log, synthetic


class FrameworkRecordTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p05-torch-record-host-only-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.value, self.request, self.native = synthetic(self.root)

    def verify(self, value=None, *, request=None, native=None, raw=None):
        value = self.value if value is None else value
        return records.verify_observations(value, self.request if request is None else request,
            **(self.native if native is None else native), raw_log=raw_log(value) if raw is None else raw)

    def reject(self, value=None, *, request=None, native=None, raw=None, message=None):
        value = self.value if value is None else value
        value = records.decode_json(records.canonical(value))
        context = self.assertRaisesRegex(ValueError, message) if message else self.assertRaises(ValueError)
        with context:
            self.verify(value, request=request, native=native, raw=raw)

    def test_both_formats_reconcile_exact_framework_and_native_totals(self):
        for fmt in ("fp16", "bf16"):
            value, request, native = synthetic(self.root / fmt, fmt)
            result = self.verify(value, request=request, native=native)
            self.assertEqual(result, {"counts": {"matmul_runs": 6, "model_runs": 10,
                "matmul_launches": 6, "model_launches": 30, "total_launches": 36},
                "matmul_words": 384, "model_hidden_words": 1280, "model_bridge_words": 640,
                "model_output_words": 640, "event_profile_pairs": 180,
                "framework_version": "2.15.0+cpu", "operator_calls": 16,
                "framework_matmul_input_bytes": 2688, "framework_result_bytes": 4096})

    def test_native_validator_receives_the_actual_unchanged_observations(self):
        with mock.patch.object(base_records, "verify_observations", wraps=base_records.verify_observations) as verify:
            self.verify()
        self.assertEqual(verify.call_count, 1)
        args, kwargs = verify.call_args
        self.assertIs(args[0], self.value["base_observations"])
        self.assertIs(args[1], self.request["base_request"])
        self.assertIs(kwargs["native_models"], self.native["native_models"])
        self.assertEqual(kwargs["raw_log"], raw_log(self.value))

    def test_outer_scope_completion_and_extra_fields_cannot_claim_unsupported_execution(self):
        for key, replacement in (("schema_version", True), ("schema_version", 2),
                                  ("contract_id", "foreign"), ("scope", "physical-fpga"),
                                  ("outcome", "fail"), ("acceptance_claimed", True)):
            value = copy.deepcopy(self.value)
            value[key] = replacement
            with self.subTest(key=key):
                self.reject(value)
        value = copy.deepcopy(self.value)
        value["invented"] = True
        self.reject(value)

    def test_framework_version_contract_schema_and_installed_adapter_are_bound(self):
        for key, replacement in (("version", "2.14.1+cpu"), ("distribution_version", "2.15.0+cu132"),
                                  ("contract_sha256", "a" * 64), ("adapter_sha256", "b" * 64),
                                  ("operator_schemas", {}), ("adapter_file", str(Path(__file__).resolve()))):
            value = copy.deepcopy(self.value)
            value["framework"][key] = replacement
            with self.subTest(key=key):
                self.reject(value)
        value = copy.deepcopy(self.value)
        value["framework"]["operator_schemas"]["matmul_v1"] += " extra"
        self.reject(value, message="schemas")
        adapter = Path(self.value["framework"]["adapter_file"])
        original = adapter.read_bytes()
        adapter.write_bytes(original + b"# altered\n")
        self.reject(message="adapter bytes")

    def test_adapter_symlinks_and_noncanonical_paths_are_rejected(self):
        original = Path(self.value["framework"]["adapter_file"])
        copied = original.with_name("different.py")
        original.rename(copied)
        original.symlink_to(copied)
        self.reject()

    def test_request_is_frozen_and_still_checks_the_original_native_fixture(self):
        for key, replacement in (("schema_version", True), ("contract_id", "foreign")):
            request = copy.deepcopy(self.request)
            request[key] = replacement
            with self.subTest(key=key):
                self.reject(request=request)
        for key, replacement in (("version", "2.15.0"), ("contract_sha256", "wrong"),
                                  ("adapter_sha256", "A" * 64)):
            request = copy.deepcopy(self.request)
            request["framework"][key] = replacement
            with self.subTest(key=key):
                self.reject(request=request)
        request = copy.deepcopy(self.request)
        request["base_request"]["matmul_cases"][0]["a_words"][0] = "00000000"
        self.reject(request=request, message="frozen fixture")
        request = copy.deepcopy(self.request)
        request["framework"]["extra"] = 0
        self.reject(request=request)

    def test_tensor_metadata_rejects_bad_shape_layout_device_type_and_gradient(self):
        mutations = (("shape", [8, 8]), ("strides", [4, 1]), ("dtype", "torch.float32"),
                     ("device", "cuda:0"), ("storage_offset", 1), ("requires_grad", True),
                     ("storage_offset", False), ("requires_grad", 0))
        for key, replacement in mutations:
            value = copy.deepcopy(self.value)
            value["framework_matmuls"][0]["b"][key] = replacement
            with self.subTest(key=key, replacement=replacement):
                self.reject(value, message="representation")
        value = copy.deepcopy(self.value)
        value["framework_matmuls"][0]["a"]["extra"] = 1
        self.reject(value, message="fields")

    def test_input_and_returned_result_bytes_cannot_be_replaced_even_with_matching_raw_logs(self):
        selections = (("framework_matmuls", "a"), ("framework_matmuls", "b"),
                      ("framework_matmuls", "result"), ("framework_models", "result"))
        for collection, field in selections:
            for replacement in ("", "00", None, "00" * 1024):
                value = copy.deepcopy(self.value)
                value[collection][0][field]["bytes"] = replacement
                with self.subTest(collection=collection, field=field, replacement=replacement):
                    self.reject(value, message="physical bytes")
            value = copy.deepcopy(self.value)
            data = value[collection][0][field]["bytes"]
            value[collection][0][field]["bytes"] = f"{int(data[:2], 16) ^ 1:02x}" + data[2:]
            self.reject(value, message="physical bytes")

    def test_framework_row_membership_iteration_and_order_are_exact(self):
        for collection in ("framework_matmuls", "framework_models"):
            mutations = (lambda rows: rows.pop(), lambda rows: rows.append(copy.deepcopy(rows[0])),
                         lambda rows: rows.reverse(), lambda rows: rows.__setitem__(1, copy.deepcopy(rows[0])),
                         lambda rows: rows[0].update(iteration=False),
                         lambda rows: rows[0].update(case_id="replacement"))
            for index, mutate in enumerate(mutations):
                value = copy.deepcopy(self.value)
                mutate(value[collection])
                with self.subTest(collection=collection, mutation=index):
                    self.reject(value)

    def test_native_launch_failure_and_model_lineage_still_fail_framework_validation(self):
        value = copy.deepcopy(self.value)
        value["base_observations"]["matmuls"][0]["trace"]["launches_enqueued"] = 0
        self.reject(value)
        value = copy.deepcopy(self.value)
        value["base_observations"]["models"][0]["record"]["trace"]["native"][1]["a_bytes"] = "00" * 128
        self.reject(value)
        value = copy.deepcopy(self.value)
        value["base_observations"]["matmuls"][0]["close_status"]["cleanup"] = 6
        self.reject(value)

    def test_raw_observation_sequence_is_complete_unique_and_file_bound(self):
        rows = raw_log(self.value).splitlines(keepends=True)
        cases = ("".join(rows[1:]), "".join([rows[0], *rows]),
                 "".join([rows[0], rows[2], rows[1], *rows[3:]]),
                 "".join([*rows[:3], rows[1], *rows[3:]]))
        for index, raw in enumerate(cases):
            with self.subTest(index=index):
                self.reject(raw=raw, message="chronology")
        value = copy.deepcopy(self.value)
        value["framework_matmuls"][0]["result"]["bytes"] = "00"
        self.reject(value, raw=raw_log(self.value), message="raw log")

    def test_ambiguous_markers_hidden_errors_and_controls_fail(self):
        valid = raw_log(self.value)
        for prefix in ("p05_torch_matmul {}", "x P05_TORCH_MODEL {}", "P05_TORCH_FRAMEWORK={}",
                       "P05_TORCH_OTHER {}", "ERROR", "runtime error:", "P05_FAILURE {}", "\x00", "\x85"):
            with self.subTest(prefix=repr(prefix)):
                self.reject(raw=prefix + "\n" + valid)

    def test_ordinary_native_log_lines_are_retained_without_rewriting(self):
        raw = "Native context ready\n" + raw_log(self.value) + "Native context released\n"
        self.assertEqual(self.verify(raw=raw)["operator_calls"], 16)

    def test_bounded_json_rejects_duplicate_float_nonfinite_and_nonbytes(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":1.5}', b'{"x":NaN}', b'{"x":Infinity}',
                    b'\xff', b'{', b'', "{}", b'[' * 2000, b'{"x":' + b'1' * 65 + b'}'):
            with self.subTest(raw=repr(raw[:30])), self.assertRaises(ValueError):
                records.decode_json(raw)
        with mock.patch.object(records, "MAX_JSON_BYTES", 8):
            with self.assertRaisesRegex(ValueError, "oversized"):
                records.decode_json(b'{"x":123}')

    def test_request_files_are_canonical_bounded_regular_and_not_overwritten(self):
        path = self.root / "request.json"
        data = records.canonical(self.request)
        path.write_bytes(data)
        self.assertEqual(records.read_request(path), self.request)
        alias = self.root / "alias.json"
        alias.symlink_to(path)
        with self.assertRaisesRegex(ValueError, "canonical"):
            records.read_request(alias)
        with self.assertRaisesRegex(ValueError, "bounded"):
            records.read_json_file(path, limit=8)
        with self.assertRaises(ValueError):
            records.read_json_file(self.root)
        self.assertEqual(path.read_bytes(), data)

    def test_pure_reader_import_does_not_import_torch_or_native_code(self):
        code = "import sys; import p05_torch_records; assert 'torch' not in sys.modules; assert 'vortex_ai' not in sys.modules"
        environment = __import__("os").environ.copy()
        environment["PYTHONPATH"] = str(Path(records.__file__).parent)
        completed = subprocess.run([sys.executable, "-B", "-c", code], env=environment,
                                   capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


class CheckerOwnershipBoundaryTests(unittest.TestCase):
    """Host-only control-flow probes; these never execute native work or Torch."""

    def test_checker_does_not_repair_an_operator_that_returns_before_native_close(self):
        for kind in ("matmul", "model"):
            with self.subTest(kind=kind):
                owner = mock.Mock()
                session = mock.Mock()
                session.pending_operations.return_value = ()
                adapter = SimpleNamespace(token=1, last_operation=owner)

                def return_while_owned(*args):
                    session.pending_operations.return_value = (owner,)
                    return object()

                torch = SimpleNamespace(float16=object(), bfloat16=object(), ops=SimpleNamespace(
                    vortex_ai=SimpleNamespace(matmul_v1=return_while_owned, fixed_mlp_v1=return_while_owned)))
                api = SimpleNamespace(Session=SimpleNamespace(open=lambda path: session),
                                      Operation=type(owner), ModelOperation=type(owner))
                adapter_module = SimpleNamespace(TorchSession=lambda native: adapter)
                request = {"base_request": {"binding": {"bundle_root": "HOST-ONLY", "format": "fp16"},
                    "matmul_cases": ([{"m": 8, "n": 4, "k": 8, "a_words": [], "b_words": []}]
                                     if kind == "matmul" else []), "model_cases": ["HOST-ONLY"]}}
                with mock.patch.object(installed_check.check, "successful"), \
                        mock.patch.object(installed_check.check, "session_identity"), \
                        mock.patch.object(installed_check.check, "memory_info"), \
                        mock.patch.object(installed_check.check, "emit"), \
                        mock.patch.object(installed_check, "_input"), \
                        mock.patch.object(installed_check, "tensor_observation"):
                    with self.assertRaisesRegex(ValueError, "returned before explicit native close"):
                        installed_check.run_matrix(request, api, torch, adapter_module, {}, {},
                                                   installed_check.check.RunState())
                owner.close.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
