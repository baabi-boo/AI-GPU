# SPDX-License-Identifier: Apache-2.0
"""Run the actual stencil argument parser without linking the GPU runtime."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import local_qualification_cases as cases


ROOT = Path(__file__).resolve().parents[2]
HARNESS = """\
#define main stencil3d_application_main
#include "tests/regression/stencil3d/main.cpp"
#undef main

int main(int argc, char **argv)
{
    parse_args(argc, argv);
    std::cout << "size=" << size << '\\n'
              << "block_size=" << block_size << '\\n'
              << "kernel_file=" << kernel_file << '\\n';
    return 0;
}
"""


class StencilCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("g++")
        if compiler is None:
            raise unittest.SkipTest("g++ unavailable; stencil3d CLI was not executed")
        temporary = tempfile.TemporaryDirectory(prefix="ai-gpu-stencil-cli-")
        cls.addClassCleanup(temporary.cleanup)
        cls.directory = Path(temporary.name)
        source = cls.directory / "stencil_cli.cpp"
        source.write_text(HARNESS, encoding="utf-8")
        cls.binary = cls.directory / "stencil_cli"
        cls.environment = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C"}
        # Discard the renamed GPU entry point; no runtime implementations are supplied.
        result = subprocess.run(
            [compiler, "-std=c++11", "-ffunction-sections", "-fdata-sections",
             "-I", str(ROOT), "-I", str(ROOT / "sw/runtime/include"), str(source),
             "-Wl,--gc-sections", "-o", str(cls.binary)],
            cwd=cls.directory, env=cls.environment, capture_output=True, text=True,
            timeout=30, check=False,
        )
        if result.returncode:
            raise AssertionError("stencil parser harness failed to compile:\n" + result.stderr)

    def run_parser(self, arguments):
        return subprocess.run(
            [str(self.binary), *arguments], cwd=self.directory, env=self.environment,
            capture_output=True, text=True, timeout=5, check=False,
        )

    def assert_parsed(self, arguments, *, size=64, block_size=2, kernel="kernel.vxbin"):
        result = self.run_parser(arguments)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout, (
            f"size={size}\nblock_size={block_size}\nkernel_file={kernel}\n"))

    def assert_usage_error(self, arguments, diagnostic):
        result = self.run_parser(arguments)
        self.assertEqual(result.returncode, 255, result.stdout + result.stderr)
        self.assertIn("Usage:", result.stdout)
        self.assertIn(diagnostic, result.stderr)
        self.assertNotIn("block_size=", result.stdout)

    def assert_geometry_error(self, arguments):
        result = self.run_parser(arguments)
        self.assertEqual(result.returncode, 255, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("matrix size and block size must be nonzero", result.stdout)
        self.assertNotIn("block_size=", result.stdout)

    def test_defaults_are_preserved(self):
        self.assert_parsed([])

    def test_frozen_axi_store_order_arguments_are_accepted(self):
        case = cases.select_cases(["axi-store-order"])[0]
        self.assert_parsed(case["args"])

    def test_block_argument_changes_value_in_both_forms(self):
        for arguments, block_size in ((["-b4"], 4), (["-b", "8"], 8)):
            with self.subTest(arguments=arguments):
                self.assert_parsed(arguments, block_size=block_size)

    def test_zero_geometry_is_rejected(self):
        for arguments in (["-b0"], ["-b", "0"], ["-n0"], ["-n", "0"],
                          ["-n0", "-b0"]):
            with self.subTest(arguments=arguments):
                self.assert_geometry_error(arguments)

    def test_malformed_block_that_converts_to_zero_is_rejected(self):
        for arguments in (["-bbogus"], ["-b", "bogus"]):
            with self.subTest(arguments=arguments):
                self.assert_geometry_error(arguments)

    def test_size_and_kernel_arguments_are_preserved(self):
        for arguments in (
                ["-n32", "-b4", "-kcustom kernel.vxbin"],
                ["-n", "32", "-b", "4", "-k", "custom kernel.vxbin"]):
            with self.subTest(arguments=arguments):
                self.assert_parsed(arguments, size=32, block_size=4,
                                   kernel="custom kernel.vxbin")

    def test_help_exits_successfully(self):
        result = self.run_parser(["-h"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("Usage:", result.stdout)
        self.assertIn("-b", result.stdout)
        self.assertNotIn("block_size=", result.stdout)

    def test_options_require_arguments(self):
        for option in ("-n", "-b", "-k"):
            with self.subTest(option=option):
                self.assert_usage_error([option], "option requires an argument")

    def test_unknown_options_are_rejected(self):
        for option in ("-z", "-t2", "--unknown"):
            with self.subTest(option=option):
                self.assert_usage_error([option], "invalid option")


if __name__ == "__main__":
    unittest.main()
