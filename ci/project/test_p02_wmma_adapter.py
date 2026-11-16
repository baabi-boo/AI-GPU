# SPDX-License-Identifier: Apache-2.0
"""Bounded UBSan tests of the real WMMA host with a byte-replay runtime.

Scenarios come directly from the independent JSON inventories, never from the
generated C++ header or an arithmetic implementation. These tests establish
host adapter behavior only; they execute no kernel, SimX processor or RTL.
"""

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import struct
import sys
import tempfile
import unittest
from uuid import uuid4

from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / "tests/regression/sgemm_tcu"
STUB = ROOT / "ci/project/fixtures/p02_wmma_runtime_stub.cpp"
INVENTORIES = (ROOT / "ci/project/fixtures/p02_layout_v1.json",
               ROOT / "ci/project/fixtures/p02_wmma_numerical_v1.json")
MIB = 1024 * 1024
MAX_TEMP_BYTES = 1024 * MIB
WORD = re.compile(r"[0-9a-f]{8}\Z")

CAPTURE_EXIT = r"""
import json
import resource
import subprocess
import sys
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
result = subprocess.run([sys.argv[1], *json.loads(sys.argv[2])], stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, check=False)
print(json.dumps({"returncode": result.returncode,
                  "output": result.stdout.decode("utf-8", errors="replace")}))
"""


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field: " + key)
        result[key] = value
    return result


def read_source_cases():
    cases = []
    for path, expected_count in zip(INVENTORIES, (20, 68)):
        data = path.read_bytes()
        if len(data) > MIB:
            raise AssertionError("Independent inventory exceeds the test input bound")
        document = json.loads(data, object_pairs_hook=unique_fields)
        if len(document["cases"]) != expected_count:
            raise AssertionError("Independent fixture inventory size changed")
        for case in document["cases"]:
            m, n, k = (case["dimensions"][key] for key in ("m", "n", "k"))
            for field, count in (("a_words", m * k // 2), ("b_words", k * n // 2),
                                 ("expected", m * n)):
                words = case[field]
                if len(words) != count or any(WORD.fullmatch(word) is None for word in words):
                    raise AssertionError("Independent fixture words are malformed")
            cases.append({**case, "m": m, "n": n, "k": k})
    if (len({case["id"] for case in cases}) != 88
            or Counter(case["format"] for case in cases) != {"fp16": 44, "bf16": 44}):
        raise AssertionError("The test requires all 88 unique independent source cases")
    return cases


def packed_words(words):
    return b"".join(struct.pack("<I", int(word, 16)) for word in words)


def scenario_bytes(case, repeats, *, a_bytes=None, b_bytes=None):
    a = packed_words(case["a_words"]) if a_bytes is None else a_bytes
    b = packed_words(case["b_words"]) if b_bytes is None else b_bytes
    expected = packed_words(case["expected"])
    return (b"P02WMMA\x01" + struct.pack("<7I", case["m"], case["n"], case["k"],
                                       len(a), len(b), len(expected), repeats)
            + a + b + expected)


class ActualWmmaHostAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if cls.compiler is None:
            raise AssertionError("The WMMA adapter tests require a C++17 host compiler and UBSan")
        temporary_root = Path(os.environ.get("TMPDIR", str(ROOT.parent))).resolve()
        temporary_root.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(prefix="p02-wmma-adapter-", dir=temporary_root)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        cls.environment = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
                           "TMPDIR": str(cls.build), "XLEN": "64",
                           "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
        cls.cases = read_source_cases()
        cls.case_by_id = {case["id"]: case for case in cls.cases}
        cls.sources = [APPLICATION / name for name in
                       ("main.cpp", "common.h", "p02_fixture_adapter.h", "p02_fixtures.h")]
        cls.sources += [STUB, *INVENTORIES, ROOT / "profiles/p02-tfr.json",
                        ROOT / "VX_config.toml", ROOT / "ci/gen_config.py",
                        ROOT / "sw/common/tensor_cfg.h", ROOT / "sw/common/rvfloats.h",
                        ROOT / "sw/runtime/include/vortex2.h"]
        cls.identities = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in cls.sources}
        cls.flags = ["-std=c++17", "-O0", "-g0", "-Wall", "-Wextra",
                     "-fsanitize=undefined", "-fno-sanitize-recover=undefined",
                     "-I", str(ROOT / "sw/runtime/include"), "-I", str(ROOT / "sw/common"),
                     "-I", str(APPLICATION)]
        cls.stub_object = cls.build / "runtime-stub.o"
        run_host_command([cls.compiler, *cls.flags, "-Werror", "-c", str(STUB),
                          "-o", str(cls.stub_object)], cwd=cls.build,
                         env=cls.environment, timeout=30)
        cls.binaries = {}
        for fmt in ("fp16", "bf16"):
            cls.compile_host(fmt)

    @classmethod
    def check_bound_and_sources(cls):
        total = sum(path.stat().st_size for path in cls.build.rglob("*") if path.is_file())
        if total > MAX_TEMP_BYTES:
            raise AssertionError("WMMA host test temporaries exceeded 1 GiB")
        for path, digest in cls.identities.items():
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise AssertionError("Source changed during the adapter test: " + str(path))

    @classmethod
    def compile_host(cls, fmt, *, config_flags=(), app_flags=(), xlen=64, output_type="fp32"):
        key = (fmt, tuple(config_flags), tuple(app_flags), xlen, output_type)
        if key in cls.binaries:
            return cls.binaries[key]
        directory = cls.build / ("variant-" + str(len(cls.binaries)))
        directory.mkdir()
        header = directory / "VX_config.h"
        run_host_command(
            [sys.executable, str(ROOT / "ci/gen_config.py"), "--config", str(ROOT / "VX_config.toml"),
             "--profile", "p02-tfr", "--profiles-dir", str(ROOT / "profiles"),
             "--xlen", "64", "--format", "cpp", "--resolved", "--output", str(header),
             "--cflags=" + " ".join(("-DVX_CFG_XLEN=64", *config_flags))],
            cwd=cls.build, env=cls.environment, timeout=10)
        binary = directory / "sgemm_tcu"
        run_host_command(
            [cls.compiler, *cls.flags, "-include", str(header), f"-DVX_CFG_XLEN={xlen}",
             f"-DVX_CFG_XLEN_{xlen}", "-DITYPE=" + fmt, "-DOTYPE=" + output_type, *app_flags,
             str(APPLICATION / "main.cpp"), str(cls.stub_object), "-o", str(binary)],
            cwd=cls.build, env=cls.environment, timeout=30)
        cls.binaries[key] = binary
        cls.check_bound_and_sources()
        return binary

    def run_app(self, case, args=None, *, repeats=2, binary=None, fault=None,
                index=None, capability=None, a_bytes=None, b_bytes=None):
        token = uuid4().hex
        scenario = self.build / (token + ".scenario")
        trace = self.build / (token + ".trace")
        scenario.write_bytes(scenario_bytes(case, repeats, a_bytes=a_bytes, b_bytes=b_bytes))
        environment = {**self.environment, "P02_STUB_SCENARIO": str(scenario),
                       "P02_STUB_TRACE": str(trace)}
        for key, value in (("P02_STUB_FAULT", fault), ("P02_STUB_INDEX", index),
                           ("P02_STUB_CAP", capability)):
            if value is not None:
                environment[key] = str(value)
        if args is None:
            args = ["-f", case["id"], "-r", str(repeats)]
        output = run_host_command(
            [sys.executable, "-c", CAPTURE_EXIT,
             str(binary or self.compile_host(case["format"])), json.dumps(args)],
            cwd=self.build, env=environment, timeout=10)
        result = json.loads(output)
        result["trace"] = trace.read_text().splitlines() if trace.exists() else []
        self.assertNotIn("runtime error:", result["output"], result["output"])
        self.check_bound_and_sources()
        return result

    def assert_markers(self, case, result, actuals, mismatches):
        output = result["output"]
        records = [json.loads(line[len("P02_RESULT "):], object_pairs_hook=unique_fields)
                   for line in output.splitlines() if line.startswith("P02_RESULT ")]
        self.assertEqual(output.count("P02_RESULT"), len(actuals), output)
        self.assertEqual(len(records), len(actuals), output)
        for iteration, (actual, mismatch, record) in enumerate(zip(actuals, mismatches, records)):
            self.assertEqual(record, {"case_id": case["id"], "format": case["format"],
                                     "m": case["m"], "n": case["n"], "k": case["k"],
                                     "iteration": iteration, "checked": case["m"] * case["n"],
                                     "mismatches": mismatch, "actual_bits": actual})
            for field in ("m", "n", "k", "iteration", "checked", "mismatches"):
                self.assertIs(type(record[field]), int)
            self.assertTrue(all(isinstance(word, str) and WORD.fullmatch(word)
                                for word in record["actual_bits"]))
        self.assertNotIn("P02_STUB_ERROR", output, output)
        self.assertNotIn("P02_STUB_CPU_CONVERSION", output, output)
        self.assertEqual(result["returncode"], 1 if any(mismatches) else 0, output)
        self.assertEqual(output.count("PASSED!"), 0 if any(mismatches) else 1, output)
        self.assertEqual(output.count("FAILED!"), 1 if any(mismatches) else 0, output)
        self.assertTrue(output.rstrip().endswith("FAILED!" if any(mismatches) else "PASSED!"), output)

    def assert_complete_trace(self, result, repeats):
        trace = result["trace"]
        self.assertEqual(trace.count("device_open"), 1, trace)
        self.assertEqual(trace.count("device_close"), 1, trace)
        self.assertEqual(trace[-1], "device_close", trace)
        self.assertEqual(trace.count("upload:A"), 1, trace)
        self.assertEqual(trace.count("upload:B"), 1, trace)
        for prefix in ("poison", "launch", "read", "wait", "release:poison",
                       "release:launch", "release:read"):
            self.assertEqual([item for item in trace if item.startswith(prefix + ":")],
                             [prefix + ":" + str(i) for i in range(repeats)], trace)
        self.assertEqual(Counter(item for item in trace if item.startswith("query:")),
                         Counter("query:" + str(cap) for cap in (7, 1, 10, 3, 2, 12)))
        for resource in ("A", "B", "C", "kernel", "module", "queue"):
            self.assertEqual(trace.count("release:" + resource), 1, trace)

    def assert_preopen_rejection(self, case, args, *, binary=None):
        result = self.run_app(case, args, binary=binary)
        self.assertGreater(result["returncode"], 0, result["output"])
        self.assertNotEqual(result["returncode"], 86, result["output"])
        self.assertEqual(result["trace"], [], result)
        self.assertIn("Error:", result["output"])
        for marker in ("open device connection", "allocate device memory", "P02_RESULT", "PASSED!",
                       "P02_STUB_CPU_CONVERSION", "P02_STUB_ERROR"):
            self.assertNotIn(marker, result["output"])
        return result

    def test_all_fixtures_upload_exact_bytes_and_check_every_output_twice(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                result = self.run_app(case)
                self.assert_markers(case, result, [case["expected"]] * 2, [0, 0])
                self.assert_complete_trace(result, 2)

    def test_default_repeat_and_explicit_three_repeats(self):
        for fmt in ("fp16", "bf16"):
            case = self.case_by_id[fmt + "-single-k00"]
            for repeats, args in ((1, ["-f" + case["id"]]),
                                  (3, ["-r3", "-f" + case["id"]])):
                with self.subTest(format=fmt, repeats=repeats):
                    result = self.run_app(case, args, repeats=repeats)
                    self.assert_markers(case, result, [case["expected"]] * repeats, [0] * repeats)
                    self.assert_complete_trace(result, repeats)

    def test_missing_writes_and_reads_cannot_reuse_a_previous_pass(self):
        for fmt in ("fp16", "bf16"):
            case = self.case_by_id[fmt + "-multi-dense_boundaries"]
            expected = case["expected"]
            poison = [f"{int(word, 16) ^ 1:08x}" for word in expected]
            last_missing = [*expected[:-1], poison[-1]]
            for fault, actuals, mismatches in (
                ("missing_all_first", [poison, expected], [128, 0]),
                ("missing_all_second", [expected, poison], [0, 128]),
                ("missing_last_second", [expected, last_missing], [0, 1]),
                ("missing_read_second", [expected, poison], [0, 128]),
            ):
                with self.subTest(format=fmt, fault=fault):
                    result = self.run_app(case, fault=fault)
                    self.assert_markers(case, result, actuals, mismatches)
                    self.assert_complete_trace(result, 2)

    def test_diagnostic_limit_does_not_limit_exact_output_comparison(self):
        case = self.case_by_id["fp16-multi-dense_boundaries"]
        poison = [f"{int(word, 16) ^ 1:08x}" for word in case["expected"]]
        result = self.run_app(case, fault="missing_all")
        self.assert_markers(case, result, [poison, poison], [128, 128])
        self.assertEqual(result["output"].count("*** error:"), 200)
        self.assertIn("Found 256 / 128 errors!", result["output"])
        self.assert_complete_trace(result, 2)

    def test_single_bit_corruption_at_every_output_position_is_reported(self):
        for fmt in ("fp16", "bf16"):
            case = self.case_by_id[fmt + "-single-dense_boundaries"]
            for index in range(len(case["expected"])):
                with self.subTest(format=fmt, index=index):
                    corrupted = case["expected"].copy()
                    corrupted[index] = f"{int(corrupted[index], 16) ^ 1:08x}"
                    result = self.run_app(case, fault="one_bit_second", index=index)
                    self.assert_markers(case, result, [case["expected"], corrupted], [0, 1])

    def test_signed_zero_and_nan_payload_bits_are_not_float_tolerance_matches(self):
        selected = [(self.case_by_id[fmt + "-numerical-zero"], "zero_sign_second", 0x80000000)
                    for fmt in ("fp16", "bf16")]
        selected.append((self.case_by_id["bf16-numerical-half_min_normal_negative"],
                         "zero_sign_second", 0x80000000))
        for fmt in ("fp16", "bf16"):
            case = next(case for case in self.cases
                        if case["format"] == fmt and "7fc00000" in case["expected"])
            selected.append((case, "one_bit_second", 1))
        for case, fault, mask in selected:
            with self.subTest(case=case["id"]):
                index = len(case["expected"]) - 1
                corrupted = case["expected"].copy()
                corrupted[index] = f"{int(corrupted[index], 16) ^ mask:08x}"
                result = self.run_app(case, fault=fault, index=index)
                self.assert_markers(case, result, [case["expected"], corrupted], [0, 1])

    def test_independent_scenario_rejects_swapped_a_lanes_and_row_major_b(self):
        for fmt in ("fp16", "bf16"):
            case = self.case_by_id[fmt + "-single-k00"]
            a = packed_words(case["a_words"])
            swapped_a = b"".join(a[i + 2:i + 4] + a[i:i + 2] for i in range(0, len(a), 4))
            b = packed_words(case["b_words"])
            elements = struct.unpack("<" + "H" * (len(b) // 2), b)
            row_b = b"".join(struct.pack("<H", elements[col * case["k"] + row])
                              for row in range(case["k"]) for col in range(case["n"]))
            self.assertNotEqual(a, swapped_a)
            self.assertNotEqual(b, row_b)
            for operand, override in (("A", {"a_bytes": swapped_a}), ("B", {"b_bytes": row_b})):
                with self.subTest(format=fmt, operand=operand):
                    result = self.run_app(case, **override)
                    self.assertEqual(result["returncode"], 86, result["output"])
                    self.assertIn(operand + " upload differs from independent JSON bytes", result["output"])
                    self.assertNotIn("P02_RESULT", result["output"])
                    self.assertNotIn("PASSED!", result["output"])

    def test_invalid_cli_is_rejected_before_device_open(self):
        case = self.case_by_id["fp16-single-k00"]
        selected = ["-f", case["id"]]
        invalid = [["-f"], ["-f", ""], ["-f", "unknown"], ["-f", "FP16-single-k00"],
                   ["-f", case["id"][:-1]], ["-q"], ["--unknown"], ["extra"],
                   [*selected, "extra"], ["extra", *selected], [*selected, "-f", case["id"]],
                   [*selected, "-f", "bf16-single-k00"], [*selected, "-r"],
                   ["-z"], ["-m", "1"], ["-n", "1"], ["-k", "1"]]
        for option in ("-m", "-n", "-k", "-r"):
            for value in ("", "0", "-1", "+1", "1x", " 1", "1 ", "1.0", "4294967296"):
                invalid.append([option, value])
        for option in ("-m", "-n", "-k"):
            invalid.extend([selected + [option, "8"], [option, "8", *selected]])
        invalid.extend([selected + ["-z"], ["-z", *selected]])
        for args in invalid:
            with self.subTest(args=args):
                self.assert_preopen_rejection(case, args)

    def test_random_matrix_products_reject_before_device_open(self):
        case = self.case_by_id["fp16-single-k00"]
        int8 = self.compile_host("int8", output_type="int32",
                                 config_flags=("-DVX_CFG_TCU_INT8_ENABLE",))
        int4 = self.compile_host("int4", output_type="int32",
                                 config_flags=("-DVX_CFG_TCU_INT4_ENABLE",))
        # INT8 A=2**32 is a reachable 4 GiB request, but its uint32 loop wraps.
        # The stub scenario is tiny and rejects any unexpected allocation.
        for name, binary, dimensions, expansion in (
            ("int8_A", int8, (65536, 4, 65536), 1),
            ("int8_B", int8, (8, 65536, 65536), 1),
            ("int8_C", int8, (65536, 65536, 16), 1),
            ("int4_A", int4, (32768, 4, 65536), 2),
            ("int4_B", int4, (8, 32768, 65536), 2),
        ):
            with self.subTest(matrix=name):
                m, n, k = dimensions
                self.assertEqual(max(m * k * expansion, k * n * expansion, m * n), 2**32)
                if expansion == 2:
                    self.assertLess(max(m * k, k * n, m * n), 2**32)
                result = self.assert_preopen_rejection(
                    case, [f"-m{m}", f"-n{n}", f"-k{k}"], binary=binary)
                self.assertIn("matrix elements exceed the uint32 indexing range", result["output"])

    def test_random_matrix_byte_overflow_rejects_before_device_open(self):
        case = self.case_by_id["fp16-single-k00"]
        for matrix, dimensions in (
            ("A", (4294967288, 4, 4294967288)),
            ("B", (8, 4294967292, 4294967288)),
            ("C", (4294967288, 4294967292, 8)),
        ):
            with self.subTest(matrix=matrix):
                m, n, k = dimensions
                byte_counts = {"A": m * k * 2, "B": k * n * 2, "C": m * n * 4}
                self.assertGreater(byte_counts[matrix], 2**64 - 1)
                result = self.assert_preopen_rejection(case, [f"-m{m}", f"-n{n}", f"-k{k}"])
                self.assertIn("matrix byte count exceeds the host address space", result["output"])

    def test_wrong_format_and_compiled_configuration_reject_before_device_open(self):
        for fmt, other in (("fp16", "bf16"), ("bf16", "fp16")):
            case = self.case_by_id[fmt + "-single-k00"]
            self.assert_preopen_rejection(case, ["-f", other + "-single-k00"])
        case = self.case_by_id["fp16-single-k00"]
        variants = (
            ("rv32", {"xlen": 32}),
            ("tcu_dpi", {"config_flags": ("-DVX_CFG_TCU_TYPE_DPI",)}),
            ("fpu_dpi", {"config_flags": ("-DVX_CFG_FPU_TYPE_DPI",)}),
            ("eight_threads", {"config_flags": ("-DVX_CFG_NUM_THREADS=8",)}),
            ("different_latency", {"config_flags": ("-DVX_CFG_TCU_LATENCY=3",)}),
            ("disabled_fp16_bank", {"config_flags": ("-DVX_CFG_TCU_FP16_DISABLE",)}),
            ("disabled_local_memory", {"config_flags": ("-DVX_CFG_LMEM_DISABLE",)}),
            ("extra_tf32_bank", {"config_flags": ("-DVX_CFG_TCU_TF32_ENABLE",)}),
            ("matrix_loads", {"config_flags": ("-DVX_CFG_EXT_LDST_MATRIX_ENABLE",)}),
            ("wgmma", {"config_flags": ("-DVX_CFG_TCU_WGMMA_ENABLE",)}),
            ("fedp2k", {"config_flags": ("-DVX_CFG_TCU_FEDP2K",)}),
            ("kunroll_two", {"app_flags": ("-DKUNROLL=2",)}),
            ("fast_math", {"app_flags": ("-ffast-math",)}),
        )
        for name, options in variants:
            with self.subTest(config=name):
                binary = self.compile_host("fp16", **options)
                self.assert_preopen_rejection(case, ["-f", case["id"]], binary=binary)
        self.assert_preopen_rejection(case, ["-f", case["id"]], binary=self.compile_host("tf32"))

    def test_incompatible_device_capabilities_reject_before_allocation(self):
        case = self.case_by_id["fp16-single-k00"]
        for capability in ("tcu", "threads", "warps", "cores", "clusters", "issue", "xlen", "lmem", "matrix"):
            with self.subTest(capability=capability):
                result = self.run_app(case, capability=capability)
                self.assertGreater(result["returncode"], 0, result["output"])
                self.assertNotEqual(result["returncode"], 86, result["output"])
                self.assertEqual(result["trace"].count("device_open"), 1)
                self.assertEqual(result["trace"][-1], "device_close")
                self.assertFalse(any(item.startswith(("allocate:", "launch:")) for item in result["trace"]))
                self.assertNotIn("P02_RESULT", result["output"])
                self.assertNotIn("PASSED!", result["output"])

    def test_conversion_abort_controls_are_live_on_the_nonfixture_path(self):
        for fmt, conversion in (("fp16", "rv_ftoh_s"), ("bf16", "rv_ftob_s")):
            with self.subTest(format=fmt):
                case = self.case_by_id[fmt + "-single-k00"]
                result = self.run_app(case, ["-m8", "-n4", "-k8"], repeats=1)
                self.assertEqual(result["returncode"], -signal.SIGABRT, result["output"])
                self.assertIn("P02_STUB_CPU_CONVERSION: " + conversion, result["output"])
                self.assertNotIn("P02_STUB_ERROR", result["output"])
                self.assertNotIn("P02_RESULT", result["output"])
                self.assertNotIn("PASSED!", result["output"])
                self.assertFalse(any(item.startswith("launch:") for item in result["trace"]))

    def test_help_does_not_open_a_device_or_emit_result_markers(self):
        case = self.case_by_id["fp16-single-k00"]
        result = self.run_app(case, ["-h"])
        self.assertEqual(result["returncode"], 0, result["output"])
        self.assertEqual(result["trace"], [])
        self.assertIn("Usage:", result["output"])
        self.assertNotIn("P02_RESULT", result["output"])
        self.assertNotIn("PASSED!", result["output"])


class GeneratedWmmaDependencyTests(unittest.TestCase):
    def test_common_header_invalidates_host_and_kernel_in_generated_makefile(self):
        make = shutil.which("make")
        self.assertIsNotNone(make, "The WMMA dependency test requires GNU make")
        temporary_root = Path(os.environ.get("TMPDIR", str(ROOT.parent))).resolve()
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="p02-wmma-dependencies-", dir=temporary_root) as temporary:
            base = Path(temporary)
            build = base / "build64"
            build.mkdir()
            marker = base / "compiler-invoked"
            guard = base / "forbidden-compiler"
            guard.write_text('#!/bin/sh\n: > "$P02_MAKE_COMPILER_SENTINEL"\nexit 97\n')
            guard.chmod(0o700)
            environment = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
                           "TMPDIR": str(base), "PYTHONDONTWRITEBYTECODE": "1",
                           "P02_MAKE_COMPILER_SENTINEL": str(marker)}
            run_host_command(
                [str(ROOT / "configure"), "--xlen=64", "--profile=p02-tfr",
                 "--osversion=ubuntu/focal", "--tooldir=" + str(base / "unused-tools"),
                 "--prefix=" + str(base / "unused-install")],
                cwd=build, env=environment, timeout=30)
            application = build / "tests/regression/sgemm_tcu"
            self.assertEqual((application / "Makefile").read_bytes(),
                             (APPLICATION / "Makefile").read_bytes())
            self.assertEqual((application.parent / "common.mk").read_bytes(),
                             (APPLICATION.parent / "common.mk").read_bytes())
            inputs = [APPLICATION / name for name in
                      ("main.cpp", "common.h", "p02_fixture_adapter.h", "p02_fixtures.h", "kernel.cpp")]
            inputs += [ROOT / "sw/common" / name for name in ("rvfloats.cpp", "softfloat_ext.cpp")]
            identities = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
            current = max(path.stat().st_mtime_ns for path in inputs) + 1
            runtime = build / "sw/runtime/libvortex.so"
            kernel_library = build / "sw/kernel/libvortex2.a"
            outputs = [application / name for name in
                       ("sgemm_tcu", "vx_start.o", "kernel.o", "kernel.elf", "kernel.vxbin",
                        "config.stamp", ".depend")]
            for path in (*outputs, runtime, kernel_library):
                path.touch()
                os.utime(path, ns=(current, current))
            # Suppress only unrelated prerequisite recipes; keep both consumer edges real.
            command = [make, "--no-print-directory", "-n", "-j1",
                       "--old-file=.depend", "--old-file=config.stamp",
                       "--old-file=" + str(runtime), "--old-file=" + str(kernel_library),
                       *[name + "=" + str(guard)
                         for name in ("CC", "CXX", "VX_CC", "VX_CXX", "VX_CP", "MAKE")],
                       "sgemm_tcu", "kernel.vxbin"]

            def dry_run(*arguments):
                output = run_host_command(command + list(arguments), cwd=application,
                                          env=environment, timeout=10)
                self.assertFalse(marker.exists(), "A dependency probe invoked a compiler or submake")
                self.assertLess(sum(path.stat().st_size for path in base.rglob("*") if path.is_file()),
                                MAX_TEMP_BYTES)
                return output

            unchanged = dry_run()
            self.assertNotIn(str(guard), unchanged, unchanged)
            changed = dry_run("--what-if=" + str(APPLICATION / "common.h"))
            self.assertIn(" -o sgemm_tcu", changed)
            self.assertIn(" -c " + str(APPLICATION / "kernel.cpp"), changed)
            self.assertIn(" -o kernel.elf", changed)
            self.assertIn("kernel.elf kernel.vxbin", changed)
            # Removing the new edge must reproduce the stale-device-kernel failure.
            missing_edge = dry_run("--what-if=" + str(APPLICATION / "common.h"), "VX_HDRS=")
            self.assertIn(" -o sgemm_tcu", missing_edge)
            self.assertNotIn(" -c " + str(APPLICATION / "kernel.cpp"), missing_edge)
            self.assertNotIn(" -o kernel.elf", missing_edge)
            self.assertNotIn("kernel.elf kernel.vxbin", missing_edge)
            self.assertFalse((base / "unused-tools").exists())
            for path, digest in identities.items():
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest,
                                 "Source changed during the dependency probe: " + str(path))


if __name__ == "__main__":
    unittest.main()
