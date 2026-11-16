# SPDX-License-Identifier: Apache-2.0
"""Kernel ISA and ABI must agree with the frozen RV64 macro configuration."""

from contextlib import contextmanager
import unittest
from unittest import mock

from hwemu_build import check_build
from hwemu_fixture import HwemuFixture
from hwemu_io import Inputs


KERNEL_ARCH = ("-march=rv64imafd", "-mabi=lp64d")


class KernelArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = HwemuFixture()
        cls.addClassCleanup(cls.fixture.close)

    @contextmanager
    def changed_record(self, path, index, transform):
        original = path.read_bytes()
        lines = original.decode("utf-8").splitlines()
        lines[index] = transform(lines[index])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            yield
        finally:
            path.write_bytes(original)

    def kernel_record(self, transform):
        path = self.fixture.build / "tests/regression/demo/config.stamp"
        return self.changed_record(path, 0, transform)

    def check(self):
        with Inputs() as inputs:
            result = check_build(inputs, self.fixture.manifest)
            inputs.recheck()
            return result

    def reject_kernel(self, transform):
        with self.kernel_record(transform), self.assertRaises(ValueError):
            self.check()

    def test_fixture_passes_without_executing_any_declared_input(self):
        path = self.fixture.build / "tests/regression/demo/config.stamp"
        kernel, host, _linker = path.read_text(encoding="utf-8").splitlines()
        runtime = (self.fixture.build / "sw/runtime/xrt_config.stamp").read_text()
        for flag in KERNEL_ARCH:
            self.assertEqual(kernel.split().count(flag), 1)
            self.assertNotIn(flag, host)
            self.assertNotIn(flag, runtime)
        with mock.patch("subprocess.Popen", side_effect=AssertionError("must remain inert")):
            self.assertIsNone(self.check())

    def test_rv32_kernel_cannot_pass_with_rv64_macros(self):
        self.reject_kernel(lambda line: line.replace(
            "-march=rv64imafd -mabi=lp64d", "-march=rv32imaf -mabi=ilp32f"))

    def test_both_driver_selections_are_required(self):
        for removed in ((KERNEL_ARCH[0],), (KERNEL_ARCH[1],), KERNEL_ARCH):
            with self.subTest(removed=removed):
                self.reject_kernel(lambda line: " ".join(
                    word for word in line.split() if word not in removed))

    def test_each_driver_value_must_match_the_frozen_architecture(self):
        variants = {
            "-march=rv64imafd": ("rv32imaf", "rv64imaf", "rv64imafdc", "rv64gc", "native", ""),
            "-mabi=lp64d": ("ilp32f", "lp64", "lp64f", "native", ""),
        }
        for flag, values in variants.items():
            for value in values:
                replacement = flag.partition("=")[0] + "=" + value
                with self.subTest(flag=flag, value=value):
                    self.reject_kernel(lambda line: line.replace(flag, replacement))

    def test_duplicate_and_conflicting_selections_are_rejected_in_either_order(self):
        for flag, alternate in zip(KERNEL_ARCH, ("-march=rv32imaf", "-mabi=ilp32f")):
            for extra in (flag, alternate, "'" + flag + "'"):
                for replacement in (flag + " " + extra, extra + " " + flag):
                    with self.subTest(flag=flag, replacement=replacement):
                        self.reject_kernel(lambda line: line.replace(flag, replacement))

    def test_option_operands_cannot_supply_kernel_architecture(self):
        for flag in KERNEL_ARCH:
            replacements = (
                "-I " + flag, "-isystem '" + flag + "'", "-MF " + flag,
                "--include-directory=" + flag,
                "-Wp," + flag, "-Xpreprocessor " + flag,
                "-Wp,-I," + flag,
                "-Xpreprocessor -I -Xpreprocessor " + flag,
                "-Xpreprocessor -MQ -Xpreprocessor " + flag,
                "-DARCH=" + flag, "-D 'ARCH=" + flag + "'",
                "--define-macro=ARCH=" + flag,
                "-I '-Xpreprocessor " + flag + "'",
            )
            for replacement in replacements:
                with self.subTest(flag=flag, replacement=replacement):
                    self.reject_kernel(lambda line: line.replace(flag, replacement))

    def test_preprocessor_architecture_flags_are_not_driver_selections(self):
        for flag in (*KERNEL_ARCH, "-march=rv32imaf", "-mabi=ilp32f"):
            for transport in ("-Wp,", "-Xpreprocessor "):
                with self.subTest(flag=flag, transport=transport):
                    self.reject_kernel(lambda line: line + " " + transport + flag)

    def test_kernel_record_rejects_opaque_transports_and_free_source_operands(self):
        suffixes = (
            "-CFLAGS '-march=rv32imaf -mabi=ilp32f'",
            '--CFLAGS="-march=rv64imafd -mabi=lp64d"',
            "-MAKEFLAGS OPT_FAST=-O3", "--MAKEFLAGS=OPT_GLOBAL=-O2",
            "-Xassembler -march=rv32imaf", "-Xlinker -melf32lriscv",
            "-Xclang -target-abi -Xclang ilp32f", "-mllvm -target-abi=ilp32f",
            "--target=riscv32-unknown-elf", "-specs=unretained.specs",
            "--config=unretained.cfg", "@unretained.rsp",
            "--language 1800-2017", "--cc", "unrelated.cpp", "unretained.o",
            "'$OUTPUT/unretained.o'", "''", ";",
        )
        for suffix in suffixes:
            with self.subTest(suffix=suffix):
                self.reject_kernel(lambda line: line + " " + suffix)

    def test_shell_equivalent_architecture_words_remain_valid(self):
        forms = (
            "'-march=rv64imafd' '-mabi=lp64d'",
            '-march="rv64imafd" -mabi="lp64d"',
            r"-march=rv64imaf\d -mabi=lp64\d",
            '-ma""rch=rv64imafd -ma""bi=lp64d',
            "-mabi=lp64d -march=rv64imafd",
        )
        for replacement in forms:
            with self.subTest(replacement=replacement):
                with self.kernel_record(lambda line: line.replace(
                        " ".join(KERNEL_ARCH), replacement)):
                    self.assertIsNone(self.check())

    def test_consumed_architecture_shaped_operands_do_not_override_driver_flags(self):
        suffix = (
            " -I -march=rv32imaf -MF -mabi=ilp32f"
            " -DARCH=-march=rv32imaf -DABI=-mabi=ilp32f"
            " -Wp,-I,-march=rv32imaf"
            " -Xpreprocessor -MQ -Xpreprocessor -mabi=ilp32f"
        )
        with self.kernel_record(lambda line: line + suffix):
            self.assertIsNone(self.check())

    def test_native_kernel_and_host_compile_options_remain_valid(self):
        source, build = str(self.fixture.source), str(self.fixture.build)
        kernel_flags = (
            " -Wall -Wextra -Wfatal-errors -Werror -Wno-unused-command-line-argument"
            " -O3 -mcmodel=medany -fno-rtti -fno-exceptions -nostartfiles -nostdlib"
            " -fdata-sections -ffunction-sections -DNDEBUG -D__VORTEX__"
            " -I" + source + "/sw/kernel/include -I" + build + "/sw -I" + build + "/hw"
        )
        host_flags = (
            " -std=c++17 -Wall -Wextra -pedantic -Wfatal-errors -Werror"
            " -DOMPI_SKIP_MPICXX -DMPICH_SKIP_MPICXX -fPIC -O2 -DNDEBUG"
            " -I" + source + "/sw/runtime/include -I" + build + "/sw -I" + build + "/hw"
        )
        runtime = self.fixture.build / "sw/runtime/xrt_config.stamp"
        demo = self.fixture.build / "tests/regression/demo/config.stamp"
        with self.changed_record(runtime, 0, lambda line: line + host_flags), \
                self.changed_record(demo, 1, lambda line: line + host_flags), \
                self.kernel_record(lambda line: line + kernel_flags):
            self.assertIsNone(self.check())


if __name__ == "__main__":
    unittest.main()
