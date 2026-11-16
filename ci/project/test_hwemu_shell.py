# SPDX-License-Identifier: Apache-2.0
"""Compiler records exclude shell expansion and operators, even as literals."""

import unittest
from unittest import mock

from hwemu_build import _configuration_flags
from hwemu_contract import CONFIGS


BUILD = "/review/build64"
SOURCE = "/review/source"
MACROS = " ".join((*CONFIGS, "-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64"))
ARCH = "-march=rv64imafd -mabi=lp64d"
WARNINGS = "-Wall -Wextra -Wfatal-errors -Werror"
INCLUDES = "-I" + SOURCE + "/sw/kernel/include -I" + BUILD + "/sw -I" + BUILD + "/hw"
KERNEL = " ".join((
    MACROS, ARCH, WARNINGS, "-Wno-unused-command-line-argument",
    "-O3 -mcmodel=medany -fno-rtti -fno-exceptions -nostartfiles -nostdlib",
    "-fdata-sections -ffunction-sections -DNDEBUG -D__VORTEX__", INCLUDES,
))
HOST = " ".join((
    MACROS, "-std=c++17", WARNINGS, "-pedantic -O2 -DNDEBUG",
    "-DOMPI_SKIP_MPICXX -DMPICH_SKIP_MPICXX", INCLUDES,
    "-I" + SOURCE + "/sw/runtime/include",
))
RECORDS = (HOST + " -fPIC", KERNEL, HOST)
NAMES = ("runtime", "kernel", "host")


class CompilerShellSyntaxTests(unittest.TestCase):
    def check(self, records):
        runtime, kernel, host = records
        demo = "\n".join((kernel, host, "-L" + BUILD + "/sw/runtime -lvortex"))
        with mock.patch("subprocess.Popen", side_effect=AssertionError("must remain inert")):
            return _configuration_flags(runtime + "\n", demo + "\n", BUILD)

    def reject_record(self, index, transform):
        records = list(RECORDS)
        records[index] = transform(records[index])
        with self.assertRaises(ValueError):
            self.check(records)

    def test_attached_control_operators_cannot_hide_in_option_operands(self):
        stems = (
            "-I.", "-I .", "-DNOTE=1", "-D NOTE=1", "-MF deps.d",
            "-Wp,-I,.", "-Xpreprocessor -I -Xpreprocessor .",
        )
        for index, name in enumerate(NAMES):
            for stem in stems:
                for operator in (";", "&", "&&", "|", "||"):
                    prefix = stem + operator
                    with self.subTest(record=name, prefix=prefix):
                        self.reject_record(index, lambda line: prefix + " " + line)

    def test_attached_redirections_are_unsupported_in_every_record(self):
        suffixes = (
            "-I.</dev/null", "-I.>/dev/null", "-I.>>/dev/null",
            "-I.2>/dev/null", "-I.<>/dev/null", "-I.>|/dev/null",
            "-I.<&0", "-I.>&1", "-I.&>/dev/null", "-I.<<EOF",
            "-DNOTE=1</dev/null", "-DNOTE=1>/dev/null", "-MF deps.d>/dev/null",
            "-Wp,-I,.>/dev/null", "-Xpreprocessor -I -Xpreprocessor .</dev/null",
        )
        for index, name in enumerate(NAMES):
            for suffix in suffixes:
                with self.subTest(record=name, suffix=suffix):
                    self.reject_record(index, lambda line: line + " " + suffix)

    def test_quoted_and_escaped_shell_literals_are_conservatively_rejected(self):
        for index, name in enumerate(NAMES):
            for operator in ";&|<>$`":
                literals = (
                    "'-DNOTE=" + operator + "'", '"-I.' + operator + '"',
                    "-I.\\" + operator,
                )
                for literal in literals:
                    with self.subTest(record=name, literal=literal):
                        self.reject_record(index, lambda line: line + " " + literal)

    def test_unbound_placeholders_cannot_consume_kernel_architecture(self):
        for variable in ("SOURCE", "BUILD", "TOOLS", "OUTPUT"):
            operand = "-I$" + variable
            with self.subTest(variable=variable, record="kernel"):
                self.reject_record(1, lambda _line: MACROS + " " + operand + " " + ARCH)
            for index in (0, 2):
                with self.subTest(variable=variable, record=NAMES[index]):
                    self.reject_record(index, lambda line: line + " " + operand)

    def test_kernel_architecture_cannot_belong_to_a_second_shell_command(self):
        for operand in ("-I.;", "-DNOTE=1;", "-I.&&", "-I.||", "-I.|"):
            with self.subTest(operand=operand):
                self.reject_record(1, lambda _line: MACROS + " " + operand + " " + ARCH)

    def test_native_records_and_ordinary_quoted_or_split_flags_remain_valid(self):
        variants = (
            RECORDS,
            tuple(" ".join("'" + word + "'" for word in line.split()) for line in RECORDS),
            tuple(" ".join("-D " + word[2:] if word.startswith("-D") else word
                           for word in line.split()).replace(
                               ARCH, '-march="rv64imafd" -mabi="lp64d"')
                  for line in RECORDS),
        )
        for index, records in enumerate(variants):
            with self.subTest(form=index):
                self.assertIsNone(self.check(records))


if __name__ == "__main__":
    unittest.main()
