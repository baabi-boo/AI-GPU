# SPDX-License-Identifier: Apache-2.0
"""Check the integer tensor oracle's wrapping arithmetic independently of RTL."""

import os
from pathlib import Path
import shutil
import tempfile
import unittest

from tensor_host_tools import run_host_command


SOURCE = Path(__file__).resolve().parents[2]


class TensorIntegerReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            raise AssertionError("A C++17 host compiler is required for tensor oracle tests")
        cls.temporary = tempfile.TemporaryDirectory(prefix="ai-gpu-integer-reference-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        cls.binary = cls.build / "int_dot_reference_test"
        cls.environment = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
                           "TMPDIR": str(cls.build)}
        common = SOURCE / "hw/unittest/common"
        run_host_command(
            [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-O2", "-DNDEBUG",
             "-fsanitize=undefined", "-fno-sanitize-recover=undefined",
             "-I", str(common), str(common / "tests/int_dot_reference_test.cpp"),
             "-o", str(cls.binary)],
            cwd=cls.build, env=cls.environment, timeout=30, max_output_bytes=65536,
        )

    def check_group(self, group, checks):
        output = run_host_command(
            [str(self.binary), group], cwd=self.build, env=self.environment,
            timeout=5, max_output_bytes=65536,
        )
        self.assertEqual(output, f"Integer reference {group}: {checks} checks, 0 failures\n")

    def test_signed_and_unsigned_wrap_boundaries(self):
        self.check_group("boundary", 12)

    def test_signed_and_unsigned_packed_operand_values(self):
        self.check_group("packed", 5)

    def test_wide_signed_modular_reference(self):
        self.check_group("reference", 4913)


if __name__ == "__main__":
    unittest.main()
