# SPDX-License-Identifier: Apache-2.0
"""Offline contracts and source-backed output oracles for local AFU cases."""

import copy
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import unittest
from unittest import mock

import local_qualification_cases as cases


ROOT = Path(__file__).resolve().parents[2]
CORE_IDS = ("demo", "reopen-cold", "reopen-warm", "axi-store-order",
            "cp-llc-port", "mm-axi-arb")
TENSOR_IDS = ("gemm-fp16", "gemm-bf16")
ALL_IDS = CORE_IDS + TENSOR_IDS
SUCCESS = {name: "PASSED!" for name in ALL_IDS}
SUCCESS.update({"reopen-cold": "Test PASSED", "reopen-warm": "Test PASSED",
                "cp-llc-port": "PASSED", "mm-axi-arb": "PASSED (0 failures)"})
SCALAR_FLAGS = [
    "-DVX_CFG_NUM_CLUSTERS=1", "-DVX_CFG_NUM_CORES=1",
    "-DVX_CFG_NUM_WARPS=4", "-DVX_CFG_NUM_THREADS=4",
    "-DVX_CFG_ISSUE_WIDTH=1", "-DVX_CFG_FPU_TYPE_STD",
    "-DVERILATOR_RESET_VALUE=1",
]


def source(name):
    return (ROOT / name).read_text(encoding="utf-8")


def case_record(identifier):
    return cases.select_cases([identifier])[0]


def arbiter_lines(random_cycles=1234, writes=1000, write_cycles=1008):
    lines = ["1. two masters, random traffic and back-pressure"]
    for seed in range(1, 9):
        message = (f"seed {seed}: all writes and reads complete in order "
                   f"({random_cycles} cycles)")
        lines.append(f"  {message:<62} PASS")
    lines.append("2. a slave that takes the data before the address")
    for seed in range(11, 15):
        message = f"seed {seed}: no deadlock, data still in address order"
        lines.append(f"  {message:<62} PASS")
    lines.append("3. single-beat writes with address and data offered together")
    message = f"one write per cycle ({writes} writes in {write_cycles} cycles)"
    lines.extend([f"  {message:<62} PASS", "PASSED (0 failures)"])
    return lines


def workload_lines(identifier):
    if identifier == "demo":
        return [
            "open device connection", "data type: integer", "number of points: 16",
            "buffer size: 64 bytes", "upload source buffer0", "upload source buffer1",
            "load kernel module", "launch kernel", "download destination buffer",
            "wait for completion", "verify result", "cleanup", "PASSED!",
        ]
    if identifier.startswith("reopen-"):
        return [f"session {index}: {stage}" for index in range(2) for stage in (
            "open device connection", "upload + launch + readback",
            "close device connection")] + ["Test PASSED"]
    if identifier == "axi-store-order":
        return [
            "open device connection", "data type: float", "matrix size: 64x64x64",
            "block size: 2x2x2", "upload source buffer0", "load kernel module",
            "start device", "download destination buffer", "wait for completion",
            "verify result", "cleanup",
            "[xrtsim] response reordering: seed=1, 73 responses returned ahead of an older ready one",
            "PASSED!",
        ]
    if identifier == "cp-llc-port":
        return ["PASSED"]
    if identifier == "mm-axi-arb":
        return arbiter_lines()
    dtype = {"gemm-fp16": ("fp16", 2), "gemm-bf16": ("bf16", 3)}[identifier]
    return [
        "open device connection", f"input data type: {dtype[0]} (id={dtype[1]})",
        "output data type: fp32 (id=0)", "matrix A: 64x64", "matrix B: 64x64",
        "matrix C: 64x64", "upload matrix A buffer", "upload matrix B buffer",
        "load kernel module", "[iter 0] launch kernel",
        "[iter 0] download destination buffer", "[iter 0] wait for completion",
        "[iter 0] verify result", "[iter 0] match (0 errors)", "cleanup", "PASSED!",
    ]


def workload_log(identifier):
    return "\n".join(workload_lines(identifier)) + "\n"


class CaseSelectionTests(unittest.TestCase):
    def test_defaults_are_the_six_core_cases_and_tensors_require_selection(self):
        self.assertEqual(cases.CONTRACT_ID, "local-afu-rv64-v1")
        self.assertEqual(cases.CORE_IDS, CORE_IDS)
        self.assertEqual(cases.TENSOR_IDS, TENSOR_IDS)
        self.assertEqual(tuple(cases.CASES), ALL_IDS)
        self.assertEqual([case["id"] for case in cases.select_cases()], list(CORE_IDS))
        self.assertEqual([case["id"] for case in cases.select_cases(TENSOR_IDS)],
                         list(TENSOR_IDS))

    def test_explicit_selection_uses_catalog_order(self):
        self.assertEqual([case["id"] for case in cases.select_cases(list(reversed(ALL_IDS)))],
                         list(ALL_IDS))
        self.assertEqual([case["id"] for case in cases.select_cases(["gemm-bf16", "demo"])],
                         ["demo", "gemm-bf16"])

    def test_selection_rejects_empty_unknown_duplicate_and_non_string_ids(self):
        invalid = ([], (), "demo", {"demo"}, {"demo": True}, 1, True,
                   ["demo", "demo"], ["unknown"], ["DEMO"], ["demo", None],
                   [1], [["demo"]], ["demo; echo bad"], ["demo\n"])
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                cases.select_cases(value)

    def test_returned_records_and_public_catalog_are_independent(self):
        original = cases.select_cases(list(ALL_IDS))
        selected = cases.select_cases(list(ALL_IDS))
        for case in selected:
            case["args"].append("--unexpected")
            case["env"]["INJECTED"] = "1"
            case["sources"].clear()
            case["artifacts"].clear()
        self.assertEqual(cases.select_cases(list(ALL_IDS)), original)
        with mock.patch.dict(cases.CASES, {"demo": {"id": "changed"}}, clear=True):
            self.assertEqual(cases.select_cases(list(ALL_IDS)), original)

    def test_every_changed_or_missing_record_field_is_rejected_by_both_consumers(self):
        for original in cases.select_cases(list(ALL_IDS)):
            for key in original:
                for operation in ("change", "remove"):
                    candidate = copy.deepcopy(original)
                    if operation == "remove":
                        del candidate[key]
                    elif isinstance(candidate[key], list):
                        candidate[key].append("unexpected")
                    elif isinstance(candidate[key], dict):
                        candidate[key]["INJECTED"] = "1"
                    else:
                        candidate[key] += "unexpected"
                    with self.subTest(case=original["id"], field=key, operation=operation):
                        with self.assertRaises(ValueError):
                            cases.command_for(candidate, 1)
                        with self.assertRaises(ValueError):
                            cases.verify_log(candidate, workload_log(original["id"]))

    def test_noncanonical_record_types_and_extra_fields_are_rejected(self):
        invalid = (None, "demo", [], {}, {"id": "demo"},
                   dict(case_record("demo"), additional=True))
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    cases.command_for(value, 1)
                with self.assertRaises(ValueError):
                    cases.verify_log(value, workload_log("demo"))

    def test_commands_are_fixed_generated_tree_argv(self):
        expected = {
            "demo": ("demo", "-n1"),
            "reopen-cold": ("reopen", "-n1 -i2"),
            "reopen-warm": ("reopen", "-n1 -i2"),
            "axi-store-order": ("stencil3d", "-n64 -b2"),
            "gemm-fp16": ("sgemm_tcu", "-m 64 -n 64 -k 64"),
            "gemm-bf16": ("sgemm_tcu", "-m 64 -n 64 -k 64"),
        }
        for identifier, (app, arguments) in expected.items():
            for jobs in (1, 2):
                with self.subTest(case=identifier, jobs=jobs):
                    self.assertEqual(cases.command_for(case_record(identifier), jobs), [
                        "./ci/blackbox.sh", "--driver=xrt", "--target=xrtsim",
                        "--app=" + app, "--args=" + arguments])
        for identifier, app in (("cp-llc-port", "cp_llc_port"),
                                ("mm-axi-arb", "mm_axi_arb")):
            for jobs in (1, 2):
                with self.subTest(case=identifier, jobs=jobs):
                    self.assertEqual(cases.command_for(case_record(identifier), jobs),
                                     ["make", f"-j{jobs}", "-C", "hw/unittest/" + app, "run"])

    def test_every_command_rejects_unbounded_or_coerced_worker_counts(self):
        for identifier in ALL_IDS:
            for jobs in (0, -1, 3, 256, None, True, False, 1.0, 2.0, "1", "2", "1;sh"):
                with self.subTest(case=identifier, jobs=jobs), self.assertRaises(ValueError):
                    cases.command_for(case_record(identifier), jobs)


class CaseSourceContractTests(unittest.TestCase):
    def test_scalar_geometry_reset_and_stress_environment_are_fixed(self):
        self.assertEqual(shlex.split(cases.SCALAR_CONFIGS), SCALAR_FLAGS)
        expected_env = {identifier: {} for identifier in ALL_IDS}
        expected_env.update({"reopen-cold": {"XRTSIM_WARM_OPEN": "0"},
                             "reopen-warm": {"XRTSIM_WARM_OPEN": "1"},
                             "axi-store-order": {"VX_MEM_RSP_REORDER": "1",
                                                 "VX_MEM_RSP_STALL": "6"}})
        for case in cases.select_cases(list(ALL_IDS)):
            with self.subTest(case=case["id"]):
                self.assertEqual(case["env"], expected_env[case["id"]])
                if case["id"] in CORE_IDS:
                    self.assertEqual(shlex.split(case["configs"]), SCALAR_FLAGS)
                    self.assertEqual(case["group"], "units" if case["kind"] == "unit" else "scalar")

    def test_source_lists_are_unique_existing_repository_files(self):
        for case in cases.select_cases(list(ALL_IDS)):
            with self.subTest(case=case["id"]):
                self.assertEqual(len(case["sources"]), len(set(case["sources"])))
                for path in case["sources"]:
                    self.assertFalse(Path(path).is_absolute())
                    self.assertNotIn("..", Path(path).parts)
                    self.assertTrue((ROOT / path).is_file(), path)
                prefix = ("hw/unittest/" if case["kind"] == "unit" else "tests/regression/")
                for name in ("Makefile", "main.cpp"):
                    self.assertIn(prefix + case["app"] + "/" + name, case["sources"])
                if case["kind"] == "app":
                    for path in ("ci/blackbox.sh", "tests/regression/common.mk",
                                 "sw/runtime/xrt/Makefile", "sw/runtime/xrt/vortex.cpp",
                                 "sim/xrtsim/Makefile", "sim/xrtsim/xrt_c.h",
                                 "sim/xrtsim/xrt_c.cpp", "sim/xrtsim/xrt_sim.h",
                                 "sim/xrtsim/xrt_sim.cpp", "sim/xrtsim/vortex_afu_shim.sv",
                                 "hw/rtl/afu/xrt/vortex_afu.v",
                                 prefix + case["app"] + "/kernel.cpp",
                                 prefix + case["app"] + "/common.h"):
                        self.assertIn(path, case["sources"])

    def test_artifacts_bind_the_actual_application_and_unit_top_names(self):
        for case in cases.select_cases(list(ALL_IDS)):
            with self.subTest(case=case["id"]):
                app = case["app"]
                if case["kind"] == "app":
                    prefix = "tests/regression/" + app + "/"
                    self.assertEqual(case["artifacts"], [
                        "sw/runtime/xrt_config.stamp", "sw/runtime/xrtsim_config.stamp",
                        "sw/runtime/libvortex.so", "sw/runtime/libvortex-xrt.so", "sw/runtime/libxrtsim.so",
                        prefix + "config.stamp", prefix + app, prefix + "kernel.vxbin"])
                else:
                    prefix = "hw/unittest/" + app + "/"
                    top = re.search(r"(?m)^TOP\s*:=\s*(\S+)$", source(prefix + "Makefile"))[1]
                    self.assertIn(prefix + top + ".sv", case["sources"])
                    self.assertIn("hw/unittest/common.mk", case["sources"])
                    self.assertIn("hw/unittest/verilator.vlt.in", case["sources"])
                    self.assertEqual(case["artifacts"],
                                     [prefix + app, prefix + "obj_dir/V" + top + ".mk"])

    def test_catalog_bindings_retain_the_original_named_workloads(self):
        for identifier, path, entry in (
                ("reopen-cold", "regression", "reopen-1"),
                ("reopen-warm", "regression", "reopen-2"),
                ("axi-store-order", "stress", "axi-store-order"),
                ("cp-llc-port", "unittest", "hw-cp-llc-port"),
                ("mm-axi-arb", "unittest", "hw-mm-axi-arb")):
            case = case_record(identifier)
            catalog_path = "ci/testcases/" + path + ".yaml"
            with self.subTest(case=identifier):
                self.assertIn(catalog_path + ":" + entry, case["catalog"])
                self.assertIn(catalog_path, case["sources"])
                self.assertRegex(source(catalog_path), r"(?m)^\s*- id: " + re.escape(entry) + r"$")
        for identifier in ("reopen-cold", "reopen-warm"):
            self.assertIn("tests/regression/reopen/start.S", case_record(identifier)["sources"])
        self.assertIn("hw/rtl/mem/VX_cp_llc_port.sv", case_record("cp-llc-port")["sources"])
        self.assertIn("hw/rtl/libs/VX_mm_axi_arb.sv", case_record("mm-axi-arb")["sources"])

    def test_tensor_specs_preserve_both_native_p01_configurations(self):
        baseline = {case["id"]: case for case in json.loads(source("ci/project/p01_baseline.json"))["cases"]}
        for identifier in TENSOR_IDS:
            case = case_record(identifier)
            prior = baseline[identifier + "-rtlsim"]
            with self.subTest(case=identifier):
                self.assertEqual(case["app"], prior["app"])
                self.assertEqual(case["args"], prior["args"])
                self.assertEqual(shlex.split(case["configs"]), prior["configs"])
                self.assertEqual(case["group"], identifier)
                self.assertEqual(prior["arithmetic"], {"tensor": "TFR", "scalar": "STD"})
                self.assertEqual(prior["reference"]["seed"], 50)
                self.assertIn("ci/project/p01_baseline.json:" + prior["id"], case["catalog"])
                self.assertIn(prior["catalog_source"] + ":" + prior["catalog_id"], case["catalog"])
                for path in ("ci/project/p01_baseline.json", "ci/testcases/tensor.yaml",
                             "sw/kernel/include/vx_tensor.h", "sw/common/tensor_cfg.h"):
                    self.assertIn(path, case["sources"])
                observed = cases.verify_log(case, workload_log(identifier))
                for key, value in prior["reference"]["tolerances"].items():
                    self.assertEqual(observed[key], value)

    def test_generated_simulation_flags_select_native_arithmetic_and_geometry(self):
        for identifier, threads, width in (("demo", 4, 1), ("gemm-fp16", 8, 2),
                                            ("gemm-bf16", 16, 1)):
            with self.subTest(case=identifier):
                result = subprocess.run([
                    sys.executable, str(ROOT / "ci/gen_config.py"), "--config",
                    str(ROOT / "VX_config.toml"), "--cflags=" + case_record(identifier)["configs"]
                    + " -DVX_CFG_XLEN=64 -DSIMULATION -DSV_DPI",
                ], cwd=ROOT, capture_output=True, text=True, timeout=15, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                flags = shlex.split(result.stdout)
                for flag in ("-DVX_CFG_XLEN=64", "-DVX_CFG_FPU_TYPE=STD",
                             "-DVX_CFG_NUM_CORES=1", "-DVX_CFG_NUM_CLUSTERS=1",
                             "-DVX_CFG_NUM_WARPS=4", f"-DVX_CFG_NUM_THREADS={threads}",
                             f"-DVX_CFG_ISSUE_WIDTH={width}"):
                    self.assertIn(flag, flags)
                self.assertNotIn("-DVX_CFG_FPU_TYPE_DPI", flags)
                if identifier in TENSOR_IDS:
                    self.assertIn("-DVX_CFG_TCU_TYPE=TFR", flags)
                    self.assertIn("-DVX_CFG_EXT_TCU_ENABLED=1", flags)
                    self.assertIn("-DVX_CFG_TCU_FP16_ENABLED=1", flags)
                    self.assertNotIn("-DVX_CFG_TCU_TYPE_DPI", flags)

    def test_synthetic_oracles_match_original_source_output_and_reference_checks(self):
        for identifier, app in (("demo", "demo"), ("axi-store-order", "stencil3d")):
            text = source("tests/regression/" + app + "/main.cpp")
            literals = re.findall(r'std::cout << "([^"\n]+)" << std::endl;', text)
            expected = [line for line in workload_lines(identifier) if line in literals]
            self.assertGreaterEqual(len(expected), 9)
            self.assertEqual([literals.index(line) for line in expected],
                             sorted(literals.index(line) for line in expected))
            self.assertIn("std::srand(50);", text)
        demo = source("tests/regression/demo/main.cpp")
        self.assertIn("uint32_t total_threads = num_cores * num_warps * num_threads;", demo)
        self.assertIn("uint32_t num_points = count * num_tasks;", demo)
        self.assertIn("if (a != b)", demo)
        self.assertIn("#define TYPE int", source("tests/regression/demo/common.h"))
        stencil = source("tests/regression/stencil3d/main.cpp")
        self.assertIn("#define FLOAT_ULP 6", stencil)
        self.assertIn("d > FLOAT_ULP", stencil)
        self.assertIn("#define TYPE float", source("tests/regression/stencil3d/common.h"))
        reopen = source("tests/regression/reopen/main.cpp")
        for stage in ("open device connection", "upload + launch + readback", "close device connection"):
            self.assertIn('"session " << iter << ": ' + stage + '"', reopen)
        self.assertIn("uint32_t num_points = count * num_cores;", reopen)
        self.assertIn('std::cout << "Test PASSED"', reopen)
        tensor = source("tests/regression/sgemm_tcu/main.cpp")
        self.assertIn("uint32_t xr = 1;", tensor)
        self.assertIn("std::srand(50);", tensor)
        self.assertIn("if (a == 0.0f && b == 0.0f)", tensor)
        self.assertIn("if (diff < 0.01f)", tensor)
        self.assertIn("double acc = 0.0;", tensor)
        self.assertIn('printf("[iter %u] %s (%d errors)\\n", iter, iter_errors ? "MISMATCH" : "match", iter_errors);', tensor)
        types = source("sw/common/tensor_cfg.h")
        for name, identity in (("fp32", 0), ("fp16", 2), ("bf16", 3)):
            self.assertRegex(types, r"struct " + name + r" \{[^}]*id = " + str(identity) + r";")


class WorkloadLogTests(unittest.TestCase):
    def reject(self, identifier, text):
        with self.assertRaises(ValueError):
            cases.verify_log(case_record(identifier), text)

    def test_all_complete_workload_oracles_are_accepted(self):
        for identifier in ALL_IDS:
            with self.subTest(case=identifier):
                result = cases.verify_log(case_record(identifier), workload_log(identifier))
                self.assertEqual(result["outcome"], "pass")
                self.assertEqual(result["case_id"], identifier)
                self.assertEqual(result["success_marker"], SUCCESS[identifier])

    def test_retained_p01_demo_and_tensor_output_are_compatible_fixtures(self):
        paths = [("demo", "xrtsim/logs/demo-xrtsim.log")]
        paths.extend((identifier, "native/logs/" + identifier + "-" + driver + ".log")
                     for identifier in TENSOR_IDS for driver in ("simx", "rtlsim"))
        for identifier, relative in paths:
            with self.subTest(case=identifier, path=relative):
                text = source("docs/project/evidence/p01/" + relative)
                self.assertEqual(cases.verify_log(case_record(identifier), text)["outcome"], "pass")

    def test_invalid_types_empty_nul_and_utf8_byte_overflow_are_rejected(self):
        for text in (None, b"PASSED\n", [], 0, "", "\0PASSED\n", "PASSED\n\0"):
            with self.subTest(text=text):
                self.reject("cp-llc-port", text)
        self.assertEqual(cases.MAX_LOG_BYTES, 16 * 1024 * 1024)
        with mock.patch.object(cases, "MAX_LOG_BYTES", 64):
            exact = "x" * 56 + "\nPASSED\n"
            self.assertEqual(len(exact.encode("utf-8")), 64)
            self.assertEqual(cases.verify_log(case_record("cp-llc-port"), exact)["outcome"], "pass")
            self.reject("cp-llc-port", "x" + exact)
            self.reject("cp-llc-port", "é" * 29 + "\nPASSED\n")

    def test_failure_evidence_contaminates_every_otherwise_passing_case(self):
        failures = ("FAILED!", "Test FAILED", "[iter 0] MISMATCH (1 errors)",
                    "*** error: [3] expected=1, actual=0", "fatal error: missing header",
                    "FAIL source.cpp:47 (cycle 8): request order", "  check *** FAIL ***",
                    "Assertion `queue.empty()' failed.", "Segmentation fault", "Aborted",
                    "core dumped", "%Error: simulation stopped", "%Error-PINMISSING: pin",
                    "Found 1 errors!", "Found 4 / 4096 errors!")
        for identifier in ALL_IDS:
            for failure in failures:
                with self.subTest(case=identifier, failure=failure):
                    self.reject(identifier, workload_log(identifier) + failure + "\n")

    def test_make_failure_after_success_cannot_qualify(self):
        for failure in ("make: *** [Makefile:41: run] Error 2",
                        "make[1]: *** [common.mk:8: run-xrt] Error 1"):
            with self.subTest(failure=failure):
                self.reject("cp-llc-port", "PASSED\n" + failure + "\n")

    def test_missing_duplicated_foreign_or_prefixed_success_is_rejected(self):
        for identifier in ALL_IDS:
            text = workload_log(identifier)
            marker = SUCCESS[identifier]
            variants = [text.replace(marker + "\n", ""), text + marker + "\n",
                        text.replace(marker + "\n", "prefix " + marker + "\n")]
            variants.extend(text + other + "\n" for other in set(SUCCESS.values()) - {marker})
            for index, modified in enumerate(variants):
                with self.subTest(case=identifier, variant=index):
                    self.reject(identifier, modified)

    def test_missing_or_duplicate_workload_stage_is_rejected(self):
        for identifier in ALL_IDS:
            lines = workload_lines(identifier)
            for index, marker in enumerate(lines):
                for operation in ("remove", "duplicate"):
                    changed = list(lines)
                    if operation == "remove":
                        del changed[index]
                    else:
                        changed.insert(index, marker)
                    with self.subTest(case=identifier, marker=marker, operation=operation):
                        self.reject(identifier, "\n".join(changed) + "\n")

    def test_adjacent_workload_stages_cannot_be_reordered(self):
        for identifier in ("demo", "reopen-cold", "reopen-warm", "axi-store-order", *TENSOR_IDS):
            lines = [line for line in workload_lines(identifier) if not line.startswith("[xrtsim]")]
            for index in range(len(lines) - 1):
                changed = list(lines)
                changed[index:index + 2] = reversed(changed[index:index + 2])
                if identifier == "axi-store-order":
                    changed.append(next(line for line in workload_lines(identifier)
                                        if line.startswith("[xrtsim]")))
                with self.subTest(case=identifier, stage=lines[index]):
                    self.reject(identifier, "\n".join(changed) + "\n")

    def test_demo_shape_and_integer_comparison_are_exact(self):
        self.assertEqual(cases.verify_log(case_record("demo"), workload_log("demo")), {
            "outcome": "pass", "case_id": "demo", "success_marker": "PASSED!",
            "points": 16, "buffer_bytes": 64, "comparison": "exact integer"})
        for old, new in (("integer", "float"), ("points: 16", "points: 1"),
                         ("points: 16", "points: 64"), ("64 bytes", "256 bytes")):
            with self.subTest(change=new):
                self.reject("demo", workload_log("demo").replace(old, new))

    def test_reopen_requires_exactly_two_complete_sessions(self):
        for identifier in ("reopen-cold", "reopen-warm"):
            text = workload_log(identifier)
            observed = cases.verify_log(case_record(identifier), text)
            self.assertEqual(observed["sessions"], 2)
            self.assertEqual(observed["points_per_session"], 1)
            self.assertEqual(observed["warm_open_requested"], identifier == "reopen-warm")
            for modified in (text.replace("session 1:", "session 2:"),
                             text + "session 2: open device connection\n",
                             text + "session 0: unexpected stage\n"):
                with self.subTest(case=identifier, text=modified):
                    self.reject(identifier, modified)

    def test_memory_stress_requires_one_positive_counter_from_requested_seed(self):
        text = workload_log("axi-store-order")
        counter = next(line for line in text.splitlines() if line.startswith("[xrtsim]"))
        for replacement in ("", counter.replace("73 responses", "0 responses"),
                            counter.replace("73 responses", "-1 responses"),
                            counter.replace("73 responses", "01 responses"),
                            counter.replace("seed=1", "seed=2"),
                            counter + "\n" + counter,
                            counter + "\n" + counter.replace("73 responses", "74 responses")):
            with self.subTest(counter=replacement):
                self.reject("axi-store-order", text.replace(counter, replacement))
        self.assertEqual(cases.verify_log(case_record("axi-store-order"), text), {
            "outcome": "pass", "case_id": "axi-store-order", "success_marker": "PASSED!",
            "matrix": [64, 64, 64], "block": [2, 2, 2], "max_ulp": 6,
            "reorder_seed": 1, "reordered_responses": 73, "response_stall_requested": 6})
        for old, new in (("64x64x64", "32x32x32"), ("2x2x2", "4x4x4"),
                         ("data type: float", "data type: integer")):
            with self.subTest(change=new):
                self.reject("axi-store-order", text.replace(old, new))

    def test_tensor_types_shapes_and_one_zero_error_iteration_are_required(self):
        for identifier in TENSOR_IDS:
            text = workload_log(identifier)
            observed = cases.verify_log(case_record(identifier), text)
            self.assertEqual(observed["shape"], [64, 64, 64])
            self.assertEqual(observed["input_dtype"], identifier[5:])
            self.assertEqual(observed["output_dtype"], "fp32")
            self.assertEqual(observed["matched_iterations"], 1)
            for old, new in (("(id=2)", "(id=3)") if identifier == "gemm-fp16" else
                             ("(id=3)", "(id=2)"),
                             ("output data type: fp32", "output data type: fp16"),
                             ("matrix A: 64x64", "matrix A: 32x64"),
                             ("matrix B: 64x64", "matrix B: 64x32"),
                             ("matrix C: 64x64", "matrix C: 32x32"),
                             ("match (0 errors)", "match (1 errors)"),
                             ("[iter 0]", "[iter 1]")):
                with self.subTest(case=identifier, change=new):
                    self.reject(identifier, text.replace(old, new))
            for extra in ("[iter 1] launch kernel", "[iter 1] match (0 errors)",
                          "[iter 2] Elapsed time: 0 ms"):
                with self.subTest(case=identifier, extra=extra):
                    self.reject(identifier, text + extra + "\n")


class UnitOracleTests(unittest.TestCase):
    def test_cp_success_covers_the_six_actual_source_test_functions(self):
        text = source("hw/unittest/cp_llc_port/main.cpp")
        main = text[text.index("int main("):]
        self.assertEqual(re.findall(r"^\s+(test_\w+)\(b\);", main, re.MULTILINE), [
            "test_launch_without_writes", "test_reads", "test_fence_holds_launch",
            "test_fence_clears", "test_write_bursts", "test_attributes"])
        self.assertIn('std::printf("PASSED\\n");', main)
        self.assertEqual(cases.verify_log(case_record("cp-llc-port"), "PASSED\n")["source_test_functions"], 6)

    def test_arbiter_fixture_matches_source_printf_formats_and_dispositions(self):
        text = source("hw/unittest/mm_axi_arb/main.cpp")
        self.assertIn('printf("  %-62s %s\\n", what, ok ? "PASS" : "*** FAIL ***");', text)
        for literal in (
                "seed %u: all writes and reads complete in order (%d cycles)",
                "seed %u: no deadlock, data still in address order",
                "one write per cycle (%d writes in %d cycles)"):
            self.assertIn('"' + literal + '"', text)
        self.assertIn("for (uint32_t seed = 1; seed <= 8; ++seed)", text)
        self.assertIn("for (uint32_t seed = 11; seed <= 14; ++seed)", text)
        self.assertIn("rng = 21;", text)
        self.assertIn("run(ms, sc, 200000, &cycles)", text)
        self.assertIn("make_master(5, STYLE_FREE, 100, 1000, 0, 0)", text)
        self.assertIn("check(ok && errors == 0 && last + 1 <= writes + 16, what);", text)
        self.assertIn('printf("\\n%s (%d failure%s)\\n", failures ? "FAILED" : "PASSED",', text)
        result = cases.verify_log(case_record("mm-axi-arb"), workload_log("mm-axi-arb"))
        self.assertEqual(result, {
            "outcome": "pass", "case_id": "mm-axi-arb", "success_marker": "PASSED (0 failures)",
            "checks_passed": 13, "random_seeds": list(range(1, 9)),
            "data_before_address_seeds": list(range(11, 15)),
            "throughput": {"writes": 1000, "cycles": 1008}})

    def test_arbiter_seed_order_section_placement_and_all_thirteen_checks_are_required(self):
        original = arbiter_lines()
        variants = []
        reordered = list(original)
        reordered[1], reordered[2] = reordered[2], reordered[1]
        variants.append(reordered)
        moved = list(original)
        first = moved.pop(1)
        moved.insert(moved.index("2. a slave that takes the data before the address") + 1, first)
        variants.append(moved)
        moved = list(original)
        data_first = moved.pop(10)
        moved.insert(1, data_first)
        variants.append(moved)
        moved = list(original)
        throughput = moved.pop(-2)
        moved.insert(1, throughput)
        variants.append(moved)
        variants.append(original[:-1] + ["  unrequested extra check PASS", original[-1]])
        for old, new in (("seed 1:", "seed 9:"), ("seed 11:", "seed 15:"),
                         ("seed 12:", "seed 11:"), (" PASS", " SKIP"),
                         (" PASS", " *** FAIL ***")):
            variants.append([line.replace(old, new) for line in original])
        for index, lines in enumerate(variants):
            with self.subTest(variant=index), self.assertRaises(ValueError):
                cases.verify_log(case_record("mm-axi-arb"), "\n".join(lines) + "\n")

    def test_arbiter_cycle_and_write_bounds_preserve_the_source_checks(self):
        for cycles, writes, write_cycles in ((1, 1000, 1000), (200000, 1000, 1016)):
            with self.subTest(random_cycles=cycles, write_cycles=write_cycles):
                text = "\n".join(arbiter_lines(cycles, writes, write_cycles)) + "\n"
                self.assertEqual(cases.verify_log(case_record("mm-axi-arb"), text)["checks_passed"], 13)
        for cycles, writes, write_cycles in ((0, 1000, 1008), (200001, 1000, 1008),
                                            (100, 999, 1008), (100, 1001, 1008),
                                            (100, 1000, 0), (100, 1000, 1017)):
            with self.subTest(random_cycles=cycles, writes=writes, write_cycles=write_cycles):
                with self.assertRaises(ValueError):
                    cases.verify_log(case_record("mm-axi-arb"),
                                     "\n".join(arbiter_lines(cycles, writes, write_cycles)) + "\n")


if __name__ == "__main__":
    unittest.main()
