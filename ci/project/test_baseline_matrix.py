# SPDX-License-Identifier: Apache-2.0
"""Offline matrix and inherited configuration/oracle contract checks."""

from contextlib import redirect_stdout
import copy
import importlib.util
import io
from pathlib import Path
import re
import shlex
import sys
import tempfile
import unittest

import baseline_matrix


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "ci/project/p01_baseline.json"
SPEC = importlib.util.spec_from_file_location(
    "baseline_matrix_gen_config", ROOT / "ci/gen_config.py")
gen_config = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gen_config
SPEC.loader.exec_module(gen_config)


class MatrixFixture(unittest.TestCase):
    def setUp(self):
        self.matrix = baseline_matrix.load_matrix(MANIFEST)

    def reject_case_value(self, key, value, index=0):
        candidate = copy.deepcopy(self.matrix)
        candidate["cases"][index][key] = value
        with self.assertRaises(ValueError):
            baseline_matrix.validate_matrix(candidate)


class BaselineMatrixContractTests(MatrixFixture):
    def test_complete_matrix_has_three_matched_simulator_rtl_pairs(self):
        self.assertEqual(len(self.matrix["cases"]), 6)
        for prefix in ("gemm-fp16", "gemm-bf16", "attention-tf32"):
            pair = [case for case in self.matrix["cases"]
                    if case["id"].startswith(prefix + "-")]
            self.assertEqual({case["driver"] for case in pair}, {"simx", "rtlsim"})
            for key in ("app", "configs", "args", "input_dtype", "output_dtype",
                        "reference", "arithmetic"):
                with self.subTest(workload=prefix, field=key):
                    self.assertEqual(pair[0][key], pair[1][key])

    def test_generated_configuration_keeps_native_arithmetic_and_geometry(self):
        expected = {"fp16": (8, 2), "bf16": (16, 1), "tf32": (4, 4)}
        for case in self.matrix["cases"]:
            with self.subTest(case=case["id"]):
                flags = baseline_matrix.config_for(case) + " -DVX_CFG_XLEN=64"
                if case["driver"] == "rtlsim":
                    flags += " -DSIMULATION -DSV_DPI"
                output = io.StringIO()
                with redirect_stdout(output):
                    result = gen_config.main([
                        "--config", str(ROOT / "VX_config.toml"), "--cflags=" + flags])
                self.assertEqual(result, 0)
                tokens = shlex.split(output.getvalue())
                threads, issue_width = expected[case["input_dtype"]]
                for token in (
                    "-DVX_CFG_XLEN=64", "-DVX_CFG_FPU_TYPE=STD",
                    "-DVX_CFG_TCU_TYPE=TFR", "-DVX_CFG_NUM_CORES=1",
                    "-DVX_CFG_NUM_CLUSTERS=1", "-DVX_CFG_NUM_WARPS=4",
                    f"-DVX_CFG_NUM_THREADS={threads}",
                    f"-DVX_CFG_ISSUE_WIDTH={issue_width}",
                    f"-DVX_CFG_NUM_TCU_BLOCKS={issue_width}",
                    f"-DVX_CFG_NUM_TCU_LANES={threads}",
                ):
                    self.assertIn(token, tokens)
                self.assertNotIn("-DVX_CFG_FPU_TYPE_DPI", tokens)
                self.assertNotIn("-DVX_CFG_TCU_TYPE_DPI", tokens)
                if case["input_dtype"] == "tf32":
                    self.assertIn("-DVX_CFG_TCU_TF32_ENABLED=1", tokens)
                    self.assertIn("-DVX_CFG_TCU_WGMMA_ENABLED=1", tokens)
                else:
                    self.assertIn("-DVX_CFG_TCU_FP16_ENABLED=1", tokens)
                    self.assertIn("-DVX_CFG_TCU_WGMMA_ENABLED=0", tokens)

    def test_native_overrides_are_needed_when_simulation_exposes_dpi(self):
        output = io.StringIO()
        with redirect_stdout(output):
            gen_config.main(["--config", str(ROOT / "VX_config.toml"),
                             "--cflags=-DVX_CFG_XLEN=64 -DSIMULATION -DSV_DPI"])
        self.assertIn("-DVX_CFG_FPU_TYPE_DPI", shlex.split(output.getvalue()))

    def test_catalog_references_exist_and_attention_shape_is_inherited(self):
        for case in self.matrix["cases"]:
            with self.subTest(case=case["id"]):
                text = (ROOT / case["catalog_source"]).read_text(encoding="utf-8")
                match = re.search(
                    r"(?ms)^- id: " + re.escape(case["catalog_id"])
                    + r"\n(.*?)(?=^- id: |\Z)", text)
                self.assertIsNotNone(match)
                self.assertIn("app: " + case["app"], match.group(1))
                self.assertTrue((ROOT / case["reference"]["oracle"]).is_file())
                if case["app"] == "flash_attn_tcu_wg":
                    self.assertIn("args: " + " ".join(case["args"]), match.group(1))
                    self.assertRegex(match.group(1), r"xlen:\s*\n\s*- 64")

    def test_declared_tolerances_and_seed_match_inherited_oracles(self):
        gemm = (ROOT / "tests/regression/sgemm_tcu/main.cpp").read_text(encoding="utf-8")
        attention = (ROOT / "tests/regression/flash_attn_tcu_wg/main.cpp").read_text(
            encoding="utf-8")
        gemm_limit = re.search(r"if\s*\(diff\s*<\s*([0-9.]+)f\)", gemm)
        attention_limits = re.search(
            r"check_output\(ref,\s*O,\s*([0-9.e-]+)f,\s*([0-9.e-]+)f\)", attention)
        self.assertIsNotNone(gemm_limit)
        self.assertIsNotNone(attention_limits)
        for case in self.matrix["cases"]:
            source = gemm if case["app"] == "sgemm_tcu" else attention
            self.assertIn(f'std::srand({case["reference"]["seed"]});', source)
            tolerance = case["reference"]["tolerances"]
            if case["app"] == "sgemm_tcu":
                self.assertEqual(tolerance["relative_error_strict_max"], float(gemm_limit[1]))
                self.assertIn("a == 0.0f && b == 0.0f", source)
            else:
                self.assertEqual(tolerance["atol"], float(attention_limits[1]))
                self.assertEqual(tolerance["rtol"], float(attention_limits[2]))

    def test_selection_preserves_manifest_order_and_does_not_change_matrix(self):
        before = copy.deepcopy(self.matrix)
        ids = [self.matrix["cases"][-1]["id"], self.matrix["cases"][0]["id"]]
        selected = baseline_matrix.select_cases(self.matrix, ids)
        self.assertEqual([case["id"] for case in selected], list(reversed(ids)))
        self.assertEqual(self.matrix, before)
        self.assertEqual(baseline_matrix.select_cases(self.matrix), self.matrix["cases"])

    def test_selection_rejects_empty_duplicate_unknown_and_nonlist_inputs(self):
        known = self.matrix["cases"][0]["id"]
        for selection in ([], [known, known], ["unknown"], known, {known}, [None], [True]):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                baseline_matrix.select_cases(self.matrix, selection)

    def test_command_interface_keeps_application_arguments_in_one_option(self):
        for case in self.matrix["cases"]:
            command = baseline_matrix.command_for(case)
            self.assertEqual(command, ["./ci/blackbox.sh", "--driver=" + case["driver"],
                                      "--app=" + case["app"],
                                      "--args=" + " ".join(case["args"])])
            self.assertEqual(shlex.split(baseline_matrix.config_for(case)), case["configs"])
            self.assertFalse(any(option.startswith(("--debug", "--vcd", "--perf"))
                                 for option in command))

    def test_manifest_validation_has_no_source_mutation(self):
        paths = (MANIFEST, ROOT / "VX_config.toml", ROOT / "ci/testcases/tensor.yaml",
                 ROOT / "ci/testcases/tensor_wg.yaml")
        before = {path: path.read_bytes() for path in paths}
        baseline_matrix.validate_matrix(self.matrix)
        for case in self.matrix["cases"]:
            baseline_matrix.command_for(case)
            baseline_matrix.config_for(case)
        self.assertEqual(before, {path: path.read_bytes() for path in paths})


class BaselineMatrixRejectionTests(MatrixFixture):
    def test_macro_injection_is_rejected_by_all_execution_interfaces(self):
        payloads = ["-DITYPE=$(touch injected)", "-DITYPE=`id`", "-DITYPE=fp16;id",
                    "-DITYPE=fp16\n-DOTHER", "-DITYPE='fp16'", "-DITYPE=fp16 && true",
                    "-DITYPE=fp16\\", "-DITYPE=fp16>output", "-DITYPE=fp16|cat"]
        for payload in payloads:
            case = copy.deepcopy(self.matrix["cases"][0])
            case["configs"].append(payload)
            for interface in (baseline_matrix.command_for, baseline_matrix.config_for):
                with self.subTest(payload=payload, interface=interface.__name__):
                    with self.assertRaises(ValueError):
                        interface(case)

    def test_argument_injection_and_dimension_changes_are_rejected(self):
        for value in ("64;id", "$(id)", "`id`", "64\n", "64 >out", "32", 64):
            args = list(self.matrix["cases"][0]["args"])
            args[1] = value
            with self.subTest(value=value):
                self.reject_case_value("args", args)
        self.reject_case_value("args", "-m 64 -n 64 -k 64")

    def test_native_backend_and_enable_flags_cannot_drift(self):
        for original, replacement in (
            ("-DVX_CFG_TCU_TYPE_TFR", "-DVX_CFG_TCU_TYPE_DPI"),
            ("-DVX_CFG_FPU_TYPE_STD", "-DVX_CFG_FPU_TYPE_DPI"),
            ("-DVX_CFG_EXT_TCU_ENABLE", "-DVX_CFG_EXT_TCU_DISABLE"),
            ("-DVX_CFG_TCU_FP16_ENABLE", "-DVX_CFG_TCU_FP16_ENABLE=0"),
            ("-DVX_CFG_NUM_THREADS=8", "-DVX_CFG_NUM_THREADS=16"),
        ):
            configs = [replacement if token == original else token
                       for token in self.matrix["cases"][0]["configs"]]
            with self.subTest(replacement=replacement):
                self.reject_case_value("configs", configs)
        self.reject_case_value("arithmetic", {"tensor": "TFR", "scalar": "DPI"})

    def test_duplicate_and_extra_macros_are_rejected(self):
        for extra in ("-DITYPE=fp16", "-DITYPE=bf16", "-DSV_DPI", "-DSIMX_FUNCTIONAL",
                      "-DVX_CFG_FPU_TYPE=DPI", "-DUNREVIEWED=1", 42):
            with self.subTest(extra=extra):
                self.reject_case_value("configs", self.matrix["cases"][0]["configs"] + [extra])

    def test_missing_or_duplicate_required_case_cannot_validate(self):
        missing = copy.deepcopy(self.matrix)
        missing["cases"].pop()
        duplicate = copy.deepcopy(self.matrix)
        duplicate["cases"][-1] = copy.deepcopy(duplicate["cases"][0])
        for candidate in (missing, duplicate):
            with self.assertRaises(ValueError):
                baseline_matrix.validate_matrix(candidate)

    def test_unknown_keys_at_each_schema_layer_are_rejected(self):
        for location in ((), ("cases", 0), ("cases", 0, "reference"),
                         ("cases", 0, "reference", "tolerances")):
            candidate = copy.deepcopy(self.matrix)
            target = candidate
            for key in location:
                target = target[key]
            target["ignored_override"] = "unsafe"
            with self.subTest(location=location), self.assertRaises(ValueError):
                baseline_matrix.validate_matrix(candidate)

    def test_identity_and_provenance_changes_require_new_contract(self):
        for key, value in (("schema_version", True), ("xlen", 32),
                           ("toolchain_tag", "latest"), ("toolchain_commit", "0" * 40),
                           ("os_bundle", "unknown"), ("id", "different")):
            candidate = copy.deepcopy(self.matrix)
            candidate[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                baseline_matrix.validate_matrix(candidate)
        for key, value in (("driver", "xrt"), ("app", "../sgemm_tcu"),
                           ("input_dtype", "bf16"), ("output_dtype", "fp16"),
                           ("catalog_source", "../outside.yaml"), ("catalog_id", "not-real")):
            with self.subTest(key=key):
                self.reject_case_value(key, value)

    def test_tolerance_loosenings_and_nonfinite_values_are_rejected(self):
        for index, key in ((0, "relative_error_strict_max"), (4, "atol"), (4, "rtol")):
            for value in (0.1, True, float("nan"), float("inf"), "0.001"):
                candidate = copy.deepcopy(self.matrix)
                candidate["cases"][index]["reference"]["tolerances"][key] = value
                with self.subTest(index=index, key=key, value=value), self.assertRaises(ValueError):
                    baseline_matrix.validate_matrix(candidate)

    def test_json_loader_rejects_duplicate_fields_and_nonfinite_constants(self):
        data = MANIFEST.read_text(encoding="utf-8")
        payloads = [data.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1', 1),
                    data.replace('"seed": 50', '"seed": 50, "seed": 50', 1),
                    data.replace('"relative_error_strict_max": 0.01',
                                 '"relative_error_strict_max": NaN', 1)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "matrix.json"
            for payload in payloads:
                path.write_text(payload, encoding="utf-8")
                with self.assertRaises(ValueError):
                    baseline_matrix.load_matrix(path)

    def test_json_loader_rejects_missing_malformed_and_oversized_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "matrix.json"
            for value in (path, Path(directory)):
                with self.assertRaises(ValueError):
                    baseline_matrix.load_matrix(value)
            for content in (b"{", b"\xff", b" " * (baseline_matrix.MAX_MANIFEST_BYTES + 1)):
                path.write_bytes(content)
                with self.assertRaises(ValueError):
                    baseline_matrix.load_matrix(path)


if __name__ == "__main__":
    unittest.main()
