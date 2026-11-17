# SPDX-License-Identifier: Apache-2.0
"""Exercise the real WGMMA host against independent byte replay and API faults.

The runtime stub checks allocation, ABI, dependencies, poison, and cleanup only.
It executes no device kernel and establishes no processor/RTL acceptance.
"""

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile
import unittest
from uuid import uuid4

from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "tests/regression/p02_wgmma"
STUB = ROOT / "ci/project/fixtures/p02_wgmma_host_stub.cpp"
CORPUS = ROOT / "ci/project/fixtures/p02_wgmma_v1.json"
WORD = re.compile(r"[0-9a-f]{8}\Z")
BASE_CONFIG = {
    "XLEN": "64", "NUM_CLUSTERS": "1", "NUM_CORES": "1", "NUM_THREADS": "8",
    "NUM_WARPS": "8", "ISSUE_WIDTH": "4", "FETCH_WIDTH": "2", "NUM_ALU_BLOCKS": "1",
    "NUM_LSU_BLOCKS": "1", "NUM_FPU_BLOCKS": "1", "NUM_TCU_BLOCKS": "4",
    "NUM_TCU_LANES": "8", "TCU_PE_RATIO": "1", "TCU_LATENCY": "4", "TCU_USE_DSP": "0",
    "LMEM_LOG_SIZE": "14", "LMEM_NUM_BANKS": "8", "TCU_TYPE": "TFR", "FPU_TYPE": "STD",
    "EXT_TCU_ENABLE": "1", "LMEM_ENABLE": "1", "TCU_FP16_ENABLE": "1",
    "TCU_WGMMA_ENABLE": "1", "TCU_TF32_DISABLE": "1", "TCU_FP8_DISABLE": "1",
    "TCU_FP4_DISABLE": "1", "TCU_INT8_DISABLE": "1", "TCU_INT4_DISABLE": "1",
    "TCU_MX_DISABLE": "1", "TCU_MXFP4_DISABLE": "1", "TCU_NVFP4_DISABLE": "1",
    "TCU_DSM_DISABLE": "1", "EXT_LDST_MATRIX_DISABLE": "1", "TCU_SPARSE_DISABLE": "1",
}
CAPTURE = r"""
import json
import resource
import subprocess
import sys
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
r = subprocess.run([sys.argv[1], *json.loads(sys.argv[2])], stdout=subprocess.PIPE,
                   stderr=subprocess.STDOUT, check=False)
print(json.dumps({"returncode": r.returncode, "output": r.stdout.decode("utf-8", errors="replace")}))
"""


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def words_bytes(words):
    if any(not isinstance(word, str) or WORD.fullmatch(word) is None for word in words):
        raise ValueError("fixture contains noncanonical words")
    return b"".join(struct.pack("<I", int(word, 16)) for word in words)


def scenario_bytes(case, changed=None):
    fields = ("a_words", "b_words", "expected", "metadata_words")
    payloads = [words_bytes(case[field]) for field in fields]
    if changed is not None:
        index = fields.index(changed)
        payload = bytearray(payloads[index])
        payload[0] ^= 1
        payloads[index] = bytes(payload)
    return (b"WGMMA01!" + struct.pack("<5I", int(case["sparse"]), *(len(p) for p in payloads))
            + b"".join(payloads))


class ActualWgmmaHostAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if cls.compiler is None:
            raise AssertionError("WGMMA adapter tests require a C++17 host compiler with UBSan")
        parent = Path(os.environ.get("TMPDIR", str(ROOT.parent))).resolve()
        parent.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(prefix="p02-wgmma-adapter-", dir=parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        cls.environment = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
                           "TMPDIR": str(cls.build), "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
        data = CORPUS.read_bytes()
        if len(data) > 1024 * 1024:
            raise AssertionError("fixture corpus exceeds the host-test bound")
        cls.cases = json.loads(data, object_pairs_hook=unique_fields)["cases"]
        if len(cls.cases) != 6 or len({case["id"] for case in cls.cases}) != 6:
            raise AssertionError("expected six unique source fixtures")
        for case in cls.cases:
            expected_counts = {"a_words": 256 if case["sparse"] else 512, "b_words": 64,
                               "expected": 512, "metadata_words": 128 if case["sparse"] else 0}
            if (case["m"], case["n"], case["k"]) != (64, 8, 16):
                raise AssertionError("unexpected fixture geometry")
            for field, count in expected_counts.items():
                if len(case[field]) != count:
                    raise AssertionError("unexpected fixture storage")
                words_bytes(case[field])
        cls.by_id = {case["id"]: case for case in cls.cases}
        cls.inputs = [APP / "main.cpp", APP / "fixtures.h", APP / "Makefile", STUB, CORPUS,
                      ROOT / "VX_config.toml", ROOT / "ci/gen_config.py",
                      ROOT / "sw/common/tensor_cfg.h", ROOT / "sw/runtime/include/vortex2.h",
                      ROOT / "tests/regression/sgemm_tcu_wg/common.h",
                      ROOT / "tests/regression/sgemm_tcu_wg_sp/common.h"]
        cls.identities = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in cls.inputs}
        cls.flags = ["-std=c++17", "-O0", "-g0", "-Wall", "-Wextra", "-Werror",
                     "-fsanitize=undefined", "-fno-sanitize-recover=undefined",
                     "-I", str(ROOT / "sw/runtime/include"), "-I", str(ROOT / "sw/common")]
        cls.stub = cls.build / "stub.o"
        run_host_command([cls.compiler, *cls.flags, "-c", str(STUB), "-o", str(cls.stub)],
                         cwd=cls.build, env=cls.environment, timeout=30)
        cls.binaries = {}
        cls.compile_host()

    @classmethod
    def check_sources_and_space(cls):
        if sum(p.stat().st_size for p in cls.build.rglob("*") if p.is_file()) > 512 * 1024 * 1024:
            raise AssertionError("host-test temporaries exceeded 512 MiB")
        for path, expected in cls.identities.items():
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise AssertionError("source changed during host test: " + str(path))

    @classmethod
    def compile_host(cls, fmt="fp16", *, sparse=False, mode="ss", row_major=False,
                     config=None, app=None, compiler_flags=()):
        config = {} if config is None else config
        app = {} if app is None else app
        key = (fmt, sparse, mode, row_major, tuple(sorted(config.items())),
               tuple(sorted(app.items())), tuple(compiler_flags))
        if key in cls.binaries:
            return cls.binaries[key]
        directory = cls.build / ("variant-" + str(len(cls.binaries)))
        directory.mkdir()
        flags = BASE_CONFIG.copy()
        if sparse:
            del flags["TCU_SPARSE_DISABLE"]
            flags["TCU_SPARSE_ENABLE"] = "1"
        flags.update(config)
        definitions = ["-DVX_CFG_" + k + "=" + v for k, v in flags.items() if v is not None]
        header = directory / "VX_config.h"
        run_host_command([sys.executable, str(ROOT / "ci/gen_config.py"), "--config",
                          str(ROOT / "VX_config.toml"), "--xlen", "64", "--format", "cpp",
                          "--resolved", "--output", str(header), "--cflags=" + " ".join(definitions)],
                         cwd=cls.build, env=cls.environment, timeout=10)
        app_flags = {"ITYPE": fmt, "OTYPE": "fp32", "WGMMA_NRC": "8", "KUNROLL": "1"}
        if mode is not None:
            app_flags["WGMMA_" + mode.upper()] = "1"
        if sparse:
            app_flags["P02_WGMMA_SPARSE"] = "1"
        if row_major:
            app_flags["WGMMA_RMAJOR_A"] = "1"
        app_flags.update(app)
        binary = directory / "p02_wgmma"
        run_host_command([cls.compiler, *cls.flags, "-include", str(header),
                          "-DVX_CFG_XLEN=" + flags["XLEN"], "-DVX_CFG_XLEN_" + flags["XLEN"] + "=1",
                          *("-D" + k + "=" + v for k, v in app_flags.items() if v is not None),
                          *compiler_flags, str(APP / "main.cpp"), str(cls.stub), "-o", str(binary)],
                         cwd=cls.build, env=cls.environment, timeout=30)
        cls.binaries[key] = binary
        cls.check_sources_and_space()
        return binary

    def run_app(self, case=None, *, binary=None, args=None, fault=None, fail=None,
                occurrence=1, capability=None, index=None, changed=None):
        case = case or self.by_id["fp16-dense-signatures-a"]
        token = uuid4().hex
        scenario = self.build / (token + ".scenario")
        trace = self.build / (token + ".trace")
        scenario.write_bytes(scenario_bytes(case, changed))
        environment = {**self.environment, "WGMMA_STUB_SCENARIO": str(scenario),
                       "WGMMA_STUB_TRACE": str(trace), "WGMMA_STUB_OCCURRENCE": str(occurrence)}
        for name, value in (("FAULT", fault), ("FAIL", fail), ("CAP", capability), ("INDEX", index)):
            if value is not None:
                environment["WGMMA_STUB_" + name] = str(value)
        if binary is None:
            binary = self.compile_host(case["format"], sparse=case["sparse"])
        if args is None:
            args = ["--case=" + case["id"], "--iterations=2"]
        result = json.loads(run_host_command([sys.executable, "-c", CAPTURE, str(binary), json.dumps(args)],
                                            cwd=self.build, env=environment, timeout=10))
        result["trace"] = trace.read_text().splitlines() if trace.exists() else []
        self.assertNotIn("runtime error:", result["output"], result["output"])
        self.check_sources_and_space()
        return result

    def markers(self, result, prefix):
        return [json.loads(line[len(prefix) + 1:], object_pairs_hook=unique_fields)
                for line in result["output"].splitlines() if line.startswith(prefix + " ")]

    def assert_complete(self, case, result, *, mode="ss", layout=None, actuals=None):
        layout = layout or ("row-major-compressed" if case["sparse"] else "block-major")
        actuals = actuals or [case["expected"], case["expected"]]
        identity = {"case_id": case["id"], "format": case["format"], "sparse": case["sparse"],
                    "mode": mode, "a_layout": layout}
        begins = self.markers(result, "P02_WGMMA_BEGIN")
        outputs = self.markers(result, "P02_WGMMA_RESULT")
        mismatches = 0
        self.assertEqual(len(begins), 2, result["output"])
        self.assertEqual(len(outputs), 2, result["output"])
        for iteration, (begin, output, actual) in enumerate(zip(begins, outputs, actuals)):
            self.assertEqual(begin, {**identity, "iteration": iteration, "m": 64, "n": 8,
                                     "k": 16, "words": 512})
            count = sum(a != e for a, e in zip(actual, case["expected"]))
            mismatches += count
            self.assertEqual(output, {**identity, "iteration": iteration, "checked": 512,
                                      "mismatches": count, "actual_bits": actual,
                                      "expected_bits": case["expected"]})
            for key in ("iteration", "checked", "mismatches"):
                self.assertIs(type(output[key]), int)
            self.assertIs(type(output["sparse"]), bool)
        self.assertEqual(result["returncode"], 1 if mismatches else 0, result["output"])
        self.assertNotIn("WGMMA_STUB_ERROR", result["output"])
        self.assertEqual(self.markers(result, "P02_WGMMA_PASS"), [] if mismatches else [
            {"case_id": case["id"], "iterations": 2, "checked": 1024}])
        trace = result["trace"]
        for kind in ("poison", "launch", "read", "wait"):
            self.assertEqual([line for line in trace if line.startswith(kind + ":")],
                             [kind + ":0", kind + ":1"], trace)
        for resource in ("A", "B", "C", "kernel", "module", "queue"):
            self.assertEqual(trace.count("create:" + resource), 1)
            self.assertEqual(trace.count("release:" + resource), 1)
        if case["sparse"]:
            self.assertEqual(trace.count("upload:metadata"), 1)
            self.assertEqual(trace.count("release:metadata"), 1)
        else:
            self.assertNotIn("upload:metadata", trace)
        self.assertEqual(Counter(line for line in trace if line.startswith("query:")),
                         Counter("query:" + str(cap) for cap in (1, 2, 12, 3, 10, 6, 7)))
        self.assertEqual(trace[-1], "device_close")
        self.assertEqual(trace.count("device_close"), 1)
        self.assertEqual(trace.count("finish"), 1)

    def assert_preopen(self, result):
        self.assertEqual(result["returncode"], 2, result["output"])
        self.assertEqual(result["trace"], [], result["output"])
        for marker in ("P02_WGMMA_BEGIN ", "P02_WGMMA_RESULT ", "P02_WGMMA_PASS "):
            self.assertNotIn(marker, result["output"])
        self.assertNotIn("WGMMA_STUB_ERROR", result["output"])

    def assert_runtime_failure(self, result):
        self.assertEqual(result["returncode"], 1, result["output"])
        self.assertNotIn("WGMMA_STUB_ERROR", result["output"])
        self.assertNotIn("P02_WGMMA_PASS", result["output"])
        self.assertIn("failed with result 10", result["output"])
        self.assertEqual(sum(line.startswith("injected:") for line in result["trace"]), 1)
        if result["trace"] != ["device_open", "injected:device_open:1"]:
            self.assertEqual(result["trace"][-1], "device_close", result["trace"])

    def test_all_six_variants_and_twelve_payload_bindings(self):
        for case in self.cases:
            variants = [("ss", False)] if case["sparse"] else [("ss", False), ("rs", False)]
            if case["format"] == "fp16" and not case["sparse"]:
                variants.append(("ss", True))
            for mode, row_major in variants:
                with self.subTest(case=case["id"], mode=mode, row_major=row_major):
                    binary = self.compile_host(case["format"], sparse=case["sparse"], mode=mode,
                                               row_major=row_major)
                    result = self.run_app(case, binary=binary)
                    self.assert_complete(case, result, mode=mode,
                                         layout="row-major" if row_major else None)

    def test_invalid_and_duplicate_arguments_reject_before_device_open(self):
        selected = "--case=fp16-dense-signatures-a"
        valid = [selected, "--iterations=2"]
        invalid = [[], [selected], ["--iterations=2"], ["--case=", "--iterations=2"],
                   ["--case=unknown", "--iterations=2"], ["--case=FP16-dense-signatures-a", "--iterations=2"],
                   valid + [selected], valid + ["--iterations=2"], valid + ["extra"],
                   ["--case", "fp16-dense-signatures-a", "--iterations=2"],
                   [selected, "--iterations", "2"], valid + ["--help"], valid + ["--m=64"],
                   valid + ["--n=8"], valid + ["--k=16"], ["--", *valid]]
        invalid += [[selected, "--iterations=" + value]
                    for value in ("", "0", "1", "3", "-2", "+2", "02", "2.0", " 2", "2 ", "2x")]
        for args in invalid:
            with self.subTest(args=args):
                self.assert_preopen(self.run_app(args=args))

    def test_argument_order_is_not_significant(self):
        case = self.by_id["fp16-dense-signatures-a"]
        self.assert_complete(case, self.run_app(case, args=["--iterations=2", "--case=" + case["id"]]))

    def test_fixture_format_and_sparse_mismatch_reject_before_device_open(self):
        for case_id, kwargs in (("bf16-dense-signatures-a", {}),
                                ("fp16-sparse-signatures-a", {}),
                                ("fp16-dense-signatures-a", {"sparse": True}),
                                ("fp16-dense-signatures-a", {"fmt": "bf16"})):
            with self.subTest(case=case_id, variant=kwargs):
                result = self.run_app(self.by_id[case_id], binary=self.compile_host(**kwargs))
                self.assert_preopen(result)
                self.assertIn("fixture does not match", result["output"])

    def test_unsupported_compile_configurations_reject_before_device_open(self):
        variants = [{"config": {"XLEN": "32"}}, {"config": {"NUM_THREADS": "4"}}, {"config": {"NUM_WARPS": "4"}},
                    {"config": {"TCU_LATENCY": "3"}}, {"config": {"FPU_TYPE": "DPI"}},
                    {"config": {"TCU_TYPE": "DPI"}}, {"mode": None},
                    {"app": {"WGMMA_RS": "1"}}, {"app": {"KUNROLL": "2"}},
                    {"sparse": True, "app": {"P02_WGMMA_SPARSE": "0"}},
                    {"sparse": True, "mode": "rs"}, {"row_major": True, "mode": "rs"},
                    {"fmt": "bf16", "row_major": True},
                    {"compiler_flags": ("-ffast-math",)}]
        for variant in variants:
            with self.subTest(variant=variant):
                case_id = ("fp16-sparse-signatures-a" if variant.get("sparse")
                           else variant.get("fmt", "fp16") + "-dense-signatures-a")
                result = self.run_app(self.by_id[case_id], binary=self.compile_host(**variant))
                self.assert_preopen(result)
                self.assertIn("invalid WGMMA configuration", result["output"])

    def test_runtime_capability_mismatch_stops_before_allocation(self):
        for capability in ("threads", "warps", "issue", "cores", "clusters", "lmem_size", "tcu",
                           "xlen", "lmem", "matrix"):
            with self.subTest(capability=capability):
                result = self.run_app(capability=capability)
                self.assertEqual(result["returncode"], 1, result["output"])
                self.assertNotIn("WGMMA_STUB_ERROR", result["output"])
                self.assertNotIn("P02_WGMMA_", result["output"])
                self.assertFalse(any(line.startswith("create:") for line in result["trace"]))
                self.assertEqual(result["trace"][-1], "device_close")

    def test_poison_detects_missing_first_second_and_partial_device_writes(self):
        case = self.by_id["fp16-dense-signatures-a"]
        poison = [[f"{base | index:08x}" for index in range(512)]
                  for base in (0x7fc10000, 0xffc20000)]
        expected = case["expected"]
        faults = {"missing_all": poison, "missing_first": [poison[0], expected],
                  "missing_second": [expected, poison[1]],
                  "missing_last_second": [expected, expected[:-1] + poison[1][-1:]],
                  "missing_read_second": [expected, poison[1]]}
        for fault, actuals in faults.items():
            with self.subTest(fault=fault):
                self.assert_complete(case, self.run_app(case, fault=fault), actuals=actuals)

    def test_one_bit_corruption_at_warp_and_output_boundaries_fails(self):
        case = self.by_id["bf16-dense-signatures-b"]
        for index in sorted({0, 1, 510, 511, *range(63, 512, 64), *range(64, 512, 64)}):
            with self.subTest(index=index):
                actual = case["expected"].copy()
                actual[index] = f"{int(actual[index], 16) ^ 1:08x}"
                self.assert_complete(case, self.run_app(case, fault="one_bit_second", index=index),
                                     actuals=[case["expected"], actual])

    def test_independent_input_bytes_detect_wrong_a_b_and_metadata_uploads(self):
        for case_id in ("fp16-dense-signatures-a", "fp16-sparse-signatures-b"):
            case = self.by_id[case_id]
            for changed in ("a_words", "b_words", *( ("metadata_words",) if case["sparse"] else ())):
                with self.subTest(case=case_id, changed=changed):
                    result = self.run_app(case, changed=changed)
                    self.assertEqual(result["returncode"], 86, result["output"])
                    self.assertIn("upload differs from independent scenario bytes", result["output"])
                    self.assertNotIn("P02_WGMMA_RESULT", result["output"])
                    self.assertNotIn("P02_WGMMA_PASS", result["output"])

    def test_setup_and_first_launch_errors_release_every_acquired_handle(self):
        operations = ("device_open", "device_query", "queue_create", "buffer_create:A",
                      "buffer_create:B", "buffer_create:C", "buffer_address:A", "buffer_address:B",
                      "buffer_address:C", "write:A", "write:B", "module_load", "kernel_get",
                      "write:C", "launch", "read", "wait", "dump_perf")
        for operation in operations:
            with self.subTest(operation=operation):
                self.assert_runtime_failure(self.run_app(fail=operation))

    def test_sparse_metadata_errors_release_every_acquired_handle(self):
        case = self.by_id["fp16-sparse-signatures-a"]
        for operation in ("buffer_create:metadata", "buffer_address:metadata", "write:metadata"):
            with self.subTest(operation=operation):
                self.assert_runtime_failure(self.run_app(case, fail=operation))

    def test_second_launch_errors_cannot_publish_success_from_first_launch(self):
        for operation in ("write:C", "launch", "read", "wait", "dump_perf",
                          "event_release:read", "event_release:launch", "event_release:poison"):
            with self.subTest(operation=operation):
                self.assert_runtime_failure(self.run_app(fail=operation, occurrence=2))

    def test_cleanup_errors_are_reported_and_do_not_publish_pass(self):
        case = self.by_id["fp16-sparse-signatures-b"]
        operations = ("queue_finish", "event_release:read", "event_release:launch",
                      "event_release:poison", "event_release:A", "event_release:B",
                      "event_release:metadata", "release:kernel", "release:module",
                      "release:metadata", "release:C", "release:B", "release:A",
                      "release:queue", "release:device")
        for operation in operations:
            with self.subTest(operation=operation):
                self.assert_runtime_failure(self.run_app(case, fail=operation))

    def test_makefile_selects_original_kernels_and_requires_explicit_mode(self):
        build = self.build / "makefile-selection"
        application = build / "tests/regression/p02_wgmma"
        application.mkdir(parents=True)
        (build / "config.mk").write_text("VORTEX_HOME := " + str(ROOT) + "\nSW_COMMON_DIR := "
                                         + str(ROOT / "sw/common") + "\n")
        (application.parent / "common.mk").write_text(
            "contract:\n\t@printf '%s\\n' '$(VX_SRCS)' '$(HDRS)' '$(VX_HDRS)' '$(KERNEL_LIB)'\n")
        for flags, kernel in (("-DWGMMA_SS=1", "sgemm_tcu_wg"),
                              ("-DWGMMA_RS", "sgemm_tcu_wg"),
                              ("-DWGMMA_SS -DP02_WGMMA_SPARSE=1", "sgemm_tcu_wg_sp")):
            with self.subTest(flags=flags):
                output = run_host_command(["make", "--no-print-directory", "-f", str(APP / "Makefile"),
                                           "contract", "CONFIGS=" + flags], cwd=application,
                                          env=self.environment, timeout=10)
                lines = output.splitlines()
                self.assertEqual(lines[0], str(ROOT / "tests/regression" / kernel / "kernel.cpp"))
                self.assertIn(str(APP / "fixtures.h"), lines[1].split())
                self.assertIn(str(ROOT / "tests/regression" / kernel / "common.h"), lines[1].split())
                self.assertIn(str(ROOT / "sw/kernel/include/vx_tensor.h"), lines[2].split())
                self.assertEqual(lines[3], "vortex2")
        output = json.loads(run_host_command([sys.executable, "-c", CAPTURE, shutil.which("make"),
                                              json.dumps(["--no-print-directory", "-f", str(APP / "Makefile"),
                                                          "contract", "CONFIGS="])],
                                             cwd=application, env=self.environment, timeout=10))
        self.assertNotEqual(output["returncode"], 0)
        self.assertIn("Select WGMMA_RS or WGMMA_SS explicitly", output["output"])


if __name__ == "__main__":
    unittest.main()
