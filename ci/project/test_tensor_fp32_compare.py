# SPDX-License-Identifier: Apache-2.0
"""Exercise the tensor harness's FP32 comparison policy with a native host binary."""

import os
from pathlib import Path
import shutil
import tempfile
import unittest

from tensor_host_tools import run_host_command


SOURCE = Path(__file__).resolve().parents[2]


class TensorFp32ComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            raise AssertionError("A C++17 host compiler is required for tensor oracle tests")
        cls.temporary = tempfile.TemporaryDirectory(prefix="ai-gpu-fp32-comparison-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        cls.binary = cls.build / "fp32_compare_test"
        cls.environment = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
                           "TMPDIR": str(cls.build)}
        common = SOURCE / "hw/unittest/common"
        run_host_command(
            [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-O2", "-DNDEBUG",
             "-fsanitize=undefined", "-fno-sanitize-recover=undefined",
             "-I", str(common), str(common / "tests/fp32_compare_test.cpp"),
             "-o", str(cls.binary)],
            cwd=cls.build, env=cls.environment, timeout=30,
        )

    def check_group(self, group):
        output = run_host_command(
            [str(self.binary), group], cwd=self.build, env=self.environment,
            timeout=5,
        )
        self.assertRegex(output,
                         rf"\AFP32 comparator {group}: [1-9][0-9]* checks, 0 failures\n\Z")

    def test_nonfinite_classes_cannot_pass_through_finite_tolerance(self):
        self.check_group("special")

    def test_finite_ulp_distances_preserve_order_without_signed_overflow(self):
        self.check_group("finite")

    def test_signed_zero_and_subnormal_boundaries(self):
        self.check_group("zero")

    def test_float_bit_representation(self):
        self.check_group("representation")


if __name__ == "__main__":
    unittest.main()
