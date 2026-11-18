# SPDX-License-Identifier: Apache-2.0
"""Host reader and compiler-profile rejection tests; no GPU execution."""

import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import tempfile
import unittest

from baseline_process import GIB, MIB, run_bounded
from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "sw/common"
HARNESS = ROOT / "ci/project/fixtures/p03_device_reader_test.cpp"


class MatmulDeviceReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if cls.compiler is None:
            raise AssertionError("Matmul reader tests require a C++17 compiler with UBSan")
        cls.temporary = tempfile.TemporaryDirectory(prefix="p03-reader-", dir=ROOT.parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        cls.binary = cls.build / "reader-test"
        cls.environment = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
                           "TMPDIR": str(cls.build), "UBSAN_OPTIONS": "halt_on_error=1"}
        cls.inputs = [HARNESS, COMMON / "ai_matmul_args.h", COMMON / "ai_matmul_profile.h"]
        cls.identities = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in cls.inputs}
        run_host_command([
            cls.compiler, "-std=c++17", "-O1", "-g0", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=undefined", "-fno-sanitize-recover=undefined", "-I", str(COMMON),
            str(HARNESS), "-o", str(cls.binary),
        ], cwd=cls.build, env=cls.environment, timeout=30)
        cls.probe = cls.build / "profile.cpp"
        cls.probe.write_text('#include <ai_matmul_profile.h>\n'
                             'static_assert(vortex::ai::kMatmulInputDType == EXPECTED_DTYPE);\n')
        resolved = run_host_command([
            sys.executable, str(ROOT / "ci/gen_config.py"),
            "--config=" + str(ROOT / "VX_config.toml"), "--profile=p02-tfr", "--xlen=64",
            "--format=cflags", "--cflags=-DVX_CFG_XLEN=64",
        ], cwd=cls.build, env=cls.environment, timeout=30)
        cls.profile_flags = shlex.split(resolved)

    def group(self, name):
        output = run_host_command([str(self.binary), name], cwd=self.build,
                                  env=self.environment, timeout=10)
        self.assertRegex(output, r"\APASS " + re.escape(name) + r" checks=[1-9][0-9]*\n\Z")
        for path, expected in self.identities.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)

    def test_literal_bytes_and_unaligned_wire_input(self):
        self.group("literal")

    def test_all_six_signatures_and_reject_shape_cross_product(self):
        self.group("signatures")

    def test_header_lengths_versions_dtype_and_atomic_failure(self):
        self.group("headers")

    def test_address_overflow_alignment_aliases_and_exact_last_byte(self):
        self.group("ranges")

    def compile_profile(self, name, extra=(), *, dtype="fp16", expected=1, diagnostic=None):
        log = self.build / (name + ".log")
        command = [self.compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-fsyntax-only",
                   "-I", str(COMMON), *self.profile_flags, "-DITYPE=" + dtype, "-DOTYPE=fp32",
                   "-DKUNROLL=1", "-DEXPECTED_DTYPE=" + str(expected), *extra, str(self.probe)]
        result = run_bounded(command, self.build, self.environment, log, timeout_seconds=30,
                             min_free_bytes=GIB, max_log_bytes=MIB, max_rss_bytes=GIB,
                             resource_paths=(self.build,))
        output = log.read_text()
        self.assertTrue(result["cleanup_complete"], output)
        self.assertTrue(result["process_started"], output)
        if diagnostic is None:
            self.assertEqual(result["outcome"], "pass", output)
            self.assertEqual(result["exit_code"], 0, output)
        else:
            self.assertEqual(result["reason"], "nonzero_exit", output)
            self.assertEqual(result["exit_code"], 1, output)
            self.assertIn(diagnostic, output)

    def test_both_formats_compile_with_resolved_accepted_profile(self):
        self.compile_profile("positive-fp16")
        self.compile_profile("positive-bf16", dtype="bf16", expected=2)

    def test_profile_rejects_wrong_arithmetic_geometry_and_missing_features(self):
        cases = [
            ("xlen", ("-UVX_CFG_XLEN", "-DVX_CFG_XLEN=32"), "ordinary WMMA RV64 geometry"),
            ("threads", ("-UVX_CFG_NUM_THREADS", "-DVX_CFG_NUM_THREADS=8"), "ordinary WMMA RV64 geometry"),
            ("no-tfr", ("-UVX_CFG_TCU_TYPE_TFR",), "native TFR/STD FP16 bank"),
            ("no-fp16", ("-UVX_CFG_TCU_FP16_ENABLE",), "native TFR/STD FP16 bank"),
            ("no-lmem", ("-UVX_CFG_LMEM_ENABLE",), "native TFR/STD FP16 bank"),
            ("no-std", ("-UVX_CFG_FPU_TYPE_STD",), "native TFR/STD FP16 bank"),
            ("dpi", ("-DVX_CFG_FPU_TYPE_DPI",), "only the native TFR/STD arithmetic"),
            ("reduction", ("-UVX_CFG_TCU_PE_RATIO", "-DVX_CFG_TCU_PE_RATIO=2"), "native TFR reduction profile"),
            ("unroll", ("-UKUNROLL", "-DKUNROLL=2"), "KUNROLL=1"),
        ]
        for name, flags, diagnostic in cases:
            with self.subTest(name=name):
                self.compile_profile(name, flags, diagnostic=diagnostic)

    def test_excluded_feature_macros_are_rejected_even_when_defined_zero(self):
        names = ["TCU_TF32_ENABLE", "TCU_FP8_ENABLE", "TCU_FP4_ENABLE", "TCU_INT8_ENABLE",
                 "TCU_INT4_ENABLE", "TCU_MX_ENABLE", "TCU_MXFP4_ENABLE", "TCU_NVFP4_ENABLE",
                 "TCU_SPARSE_ENABLE", "TCU_DSM_ENABLE", "TCU_WGMMA_ENABLE", "TCU_FEDP2K",
                 "EXT_LDST_MATRIX_ENABLE"]
        for name in names:
            with self.subTest(name=name):
                self.compile_profile(name, ("-DVX_CFG_" + name + "=0",),
                                     diagnostic="ordinary WMMA format and feature exclusions")


if __name__ == "__main__":
    unittest.main()
