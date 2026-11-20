# SPDX-License-Identifier: Apache-2.0
"""Real app guards and C++/Python synthetic schema integration; no GPU execution."""

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import tempfile
import unittest

import p04_execution_records as records
from p04_fixture_adapter import load_cases
from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "ci/project/fixtures/p04_app_contract_test.cpp"
BINDING = "0123456789abcdef" * 4
REVISION = "1234567890abcdef" * 2 + "12345678"
FIXTURE = ROOT / "ci/project/fixtures/p04_tiny_mlp_v1.json"


class ModelApplicationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            raise AssertionError("Model app tests require a C++17 compiler with UBSan")
        cls.temporary = tempfile.TemporaryDirectory(prefix="p04-app-host-", dir=ROOT.parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        cls.environment = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
                           "TMPDIR": str(cls.build), "UBSAN_OPTIONS": "halt_on_error=1"}
        inputs = [HARNESS, Path(__file__), FIXTURE, ROOT / "VX_config.toml",
                  ROOT / "ci/gen_config.py", ROOT / "ci/project/p04_fixture_adapter.py",
                  ROOT / "ci/project/p04_execution_records.py",
                  ROOT / "tests/regression/ai_mlp/main.cpp",
                  ROOT / "tests/regression/ai_mlp/records.h",
                  ROOT / "tests/regression/ai_mlp/p04_fixtures.h",
                  ROOT / "sw/runtime/ai/mlp_runtime.h", ROOT / "sw/runtime/ai/mlp_host.h",
                  ROOT / "sw/runtime/ai/runtime.h", ROOT / "sw/runtime/ai/contract.h",
                  ROOT / "sw/runtime/include/vortex2.h",
                  ROOT / "sw/common/ai_matmul_args.h", ROOT / "sw/common/ai_matmul_profile.h"]
        cls.identities = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
        cls.fixture_sha = cls.identities[FIXTURE]
        cls.cases = load_cases()
        resolved = run_host_command([
            sys.executable, str(ROOT / "ci/gen_config.py"),
            "--config=" + str(ROOT / "VX_config.toml"), "--profile=p02-tfr", "--xlen=64",
            "--format=cflags", "--cflags=-DVX_CFG_XLEN=64",
        ], cwd=cls.build, env=cls.environment, timeout=30)
        cls.binaries = {}
        for dtype in ("fp16", "bf16"):
            binary = cls.build / ("app-contract-" + dtype)
            run_host_command([
                compiler, "-std=c++17", "-O1", "-g0", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=undefined", "-fno-sanitize-recover=undefined", "-pthread",
                "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
                "-I", str(ROOT / "sw/common"), "-I", str(ROOT / "sw/runtime/include"),
                "-I", str(ROOT / "sw/runtime/ai"), *shlex.split(resolved),
                "-DITYPE=" + dtype, "-DOTYPE=fp32", "-DKUNROLL=1",
                str(HARNESS), "-o", str(binary),
            ], cwd=cls.build, env=cls.environment, timeout=45)
            cls.binaries[dtype] = binary
        cls.modules = cls.build / "module-inputs"
        cls.modules.mkdir()
        for size in (0, 15, 16, 64, 16 * 1024 * 1024, 16 * 1024 * 1024 + 1):
            with (cls.modules / ("module-" + str(size))).open("wb") as stream:
                stream.truncate(size)
                if size:
                    stream.write(b"\x12")
                    stream.seek(size - 1)
                    stream.write(b"\xab")

    def tearDown(self):
        for path, identity in self.identities.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), identity, str(path))
        self.assertLess(sum(path.stat().st_size for path in self.build.rglob("*") if path.is_file()),
                        64 * 1024 * 1024)

    def command(self, dtype, *arguments):
        return run_host_command([str(self.binaries[dtype]), *map(str, arguments)],
                                cwd=self.build, env=self.environment, timeout=10)

    def group(self, name, *arguments):
        for dtype in self.binaries:
            with self.subTest(dtype=dtype):
                self.assertRegex(self.command(dtype, name, *arguments),
                                 r"\APASS " + re.escape(name) + r" checks=[1-9][0-9]*\n\Z")

    def test_actual_cli_missing_duplicate_malformed_and_backend_bindings(self):
        self.group("cli")

    def test_module_read_exact_minimum_maximum_and_rejected_extents(self):
        self.group("modules", self.modules)

    def test_native_app_format_and_module_guards_precede_stubbed_create(self):
        self.group("guards", self.modules)

    def test_observed_profile_flags_event_results_and_monotonicity(self):
        self.group("profiles")

    def test_serializer_rejects_each_array_extent_before_read(self):
        self.group("extents")

    def test_serializer_escaping_unsigned_widths_and_exact_array_prefixes(self):
        for dtype in self.binaries:
            with self.subTest(dtype=dtype):
                raw = self.command(dtype, "edges")
                self.assertIn(r"\u0000\u0001\u001f", raw)
                row = json.loads(raw)
                trace = row["trace"]
                self.assertEqual(trace["case_id"], 'quote"\\tab\tline\n\x00\x01\x1fé')
                self.assertEqual(trace["input_dtype"], "unknown")
                self.assertEqual(trace["hidden_words"][0], "ffffffff")
                self.assertEqual(trace["hidden_words"][-1], "80000000")
                self.assertEqual(trace["bridge_bytes"], "ff" + "00" * 254 + "80")
                self.assertIs(type(trace["create_begin_ns"]), int)
                self.assertEqual(trace["create_begin_ns"], 2**64 - 1)
                for index, stage in enumerate(trace["native"]):
                    self.assertEqual(stage["operation_id"], "")
                    self.assertEqual(stage["a_bytes"], "ab" * (512 if index == 2 else index))
                    self.assertEqual(stage["b_bytes"], "cd" * (256 if index == 2 else index))
                    self.assertEqual(stage["output_words"], ["80000001"] * (128 if index == 2 else index))
                    self.assertIs(type(stage["submitted"]), bool)
                    self.assertFalse(stage["submitted"])
                    dispatch = stage["dispatch"]
                    self.assertEqual(dispatch["input_dtype"], "fp32")
                    self.assertEqual(dispatch["argument_bytes"], "00" * 56)
                    self.assertIs(type(dispatch["wait_calls"]), int)
                    self.assertEqual(dispatch["wait_calls"], 2**64 - 1)
                    self.assertEqual(len(dispatch["event_results"]), 5)
                    self.assertEqual(dispatch["event_profile_queried"], [False] * 5)

    def verify(self, output, case, backend):
        return records.verify_output(output, case, 2, BINDING, backend=backend,
                                     source_revision=REVISION, fixture_sha256=self.fixture_sha)

    def test_cpp_serializer_python_verifier_all_fixtures_backends_and_two_poisons(self):
        for case in self.cases:
            for backend in ("simx", "rtlsim"):
                with self.subTest(case=case["id"], backend=backend):
                    output = self.command(case["format"], "synthetic", case["id"], backend)
                    self.assertTrue(output.startswith("host-only synthetic record fixture; no GPU execution\n"))
                    rows = self.verify(output, case, backend)
                    self.assertEqual([row["trace"]["poison"] for row in rows],
                                     [0x7FC0DEAD, 0xDEADBEEF])
                    self.assertEqual([row["iteration"] for row in rows], [0, 1])
                    # The strict consumer validates all keys and types. Distinct
                    # synthetic observations also expose swapped duration fields.
                    for iteration, row in enumerate(rows):
                        trace = row["trace"]
                        epoch = iteration * 10000
                        observations = {"create_begin_ns": epoch + 100, "create_end_ns": epoch + 200,
                                        "advance_ns": 4000, "bridge_ns": 11, "bridge_compare_ns": 12,
                                        "assembly_ns": 13, "output_compare_ns": 14, "close_ns": 15}
                        self.assertEqual({key: trace[key] for key in observations}, observations)
                        self.assertEqual(trace["resources"], {
                            "before_valid": True, "after_valid": True,
                            "before_status": 0, "after_status": 0, "free_before": 0x100000,
                            "used_before": 0x20000, "free_after": 0x100000, "used_after": 0x20000})
                        for index, stage in enumerate(trace["native"]):
                            begin = epoch + 1000 + index * 1000
                            expected = {"submit_begin_ns": begin, "submit_end_ns": begin + 10,
                                        "wait_ns": 100, "compare_ns": 16 + index, "close_ns": 19 + index}
                            self.assertEqual({key: stage[key] for key in expected}, expected)
                            self.assertFalse(stage["submission"]["complete"])
                            self.assertEqual(stage["dispatch"]["wait_calls"], 1)
                            self.assertEqual(stage["dispatch"]["timed_out_waits"], 0)
                            self.assertEqual(stage["dispatch"]["event_profiles"], [
                                {"queued_ns": begin + event, "submit_ns": begin + 20 + event * 10,
                                 "start_ns": begin + 22 + event * 10, "end_ns": begin + 25 + event * 10}
                                for event in range(5)])

    def test_cross_language_wire_lineage_and_profile_corruption_are_rejected(self):
        for dtype in self.binaries:
            case = next(case for case in self.cases if case["id"] == dtype + "-split_boundary")
            original = self.verify(self.command(dtype, "synthetic", case["id"], "simx"), case, "simx")
            for kind in ("wire", "lineage", "profile-query", "profile-order"):
                with self.subTest(dtype=dtype, corruption=kind):
                    rows = copy.deepcopy(original)
                    stage = rows[1]["trace"]["native"][1]
                    dispatch = stage["dispatch"]
                    if kind == "wire":
                        dispatch["argument_bytes"] = "02" + dispatch["argument_bytes"][2:]
                    elif kind == "lineage":
                        stage["a_bytes"] = f"{int(stage['a_bytes'][:2], 16) ^ 1:02x}" + stage["a_bytes"][2:]
                    elif kind == "profile-query":
                        dispatch["event_profile_queried"][4] = False
                    else:
                        dispatch["event_profiles"][4]["end_ns"] = 0
                    output = "host-only corrupted synthetic fixture\n" + "".join(
                        "P04_RESULT " + json.dumps(row, separators=(",", ":")) + "\n" for row in rows) + "PASSED!\n"
                    with self.assertRaises(ValueError):
                        self.verify(output, case, "simx")


if __name__ == "__main__":
    unittest.main()
