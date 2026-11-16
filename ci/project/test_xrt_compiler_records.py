# SPDX-License-Identifier: Apache-2.0
"""File-backed regressions for effective XRT compilation records."""

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import xrt_inventory
from xrt_test_support import compiler_stamps, write_file


REQUIRED = (
    "-DVX_CFG_NUM_CLUSTERS=1", "-DVX_CFG_NUM_CORES=1",
    "-DVX_CFG_NUM_WARPS=4", "-DVX_CFG_NUM_THREADS=4",
    "-DVX_CFG_ISSUE_WIDTH=1", "-DVX_CFG_FPU_TYPE_STD",
    "-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64",
)
COMPILER_ROLES = ("runtime", "kernel", "host")


class XrtCompilerRecordTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ai-gpu-xrt-stamps-")
        self.addCleanup(temporary.cleanup)
        self.build = Path(temporary.name) / "build64"
        self.paths = {
            "runtime": "sw/runtime/xrt_config.stamp",
            "demo": "tests/regression/demo/config.stamp",
        }
        self.good = compiler_stamps(self.build)
        self.write_stamps(self.good)
        for relative in (
            "tests/regression/demo/demo", "tests/regression/demo/kernel.vxbin",
            "sw/runtime/libvortex.so", "sw/runtime/libvortex-xrt.so",
        ):
            write_file(self.build / relative, b"INERT FILE-BACKED TEST OUTPUT\n",
                       executable=relative == "tests/regression/demo/demo")

    def write_stamps(self, stamps):
        for name, relative in self.paths.items():
            write_file(self.build / relative, stamps[name])

    def inspect(self):
        with mock.patch("subprocess.Popen", side_effect=AssertionError("inspection launched a process")), \
                mock.patch("os.system", side_effect=AssertionError("inspection launched a shell")), \
                mock.patch("glob.glob", side_effect=AssertionError("inspection expanded a glob")):
            return xrt_inventory.inspect_effective(self.build)

    def changed(self, role, transform):
        stamps = dict(self.good)
        if role == "runtime":
            stamps[role] = transform(stamps[role].rstrip("\n")) + "\n"
        else:
            lines = stamps["demo"].split("\n")
            index = {"kernel": 0, "host": 1, "linker": 2}[role]
            lines[index] = transform(lines[index])
            stamps["demo"] = "\n".join(lines)
        return stamps

    def assertRejected(self, stamps, reason):
        self.write_stamps(stamps)
        report = self.inspect()
        self.assertEqual(report["outcome"], "blocked", report)
        self.assertIs(report["native_flags_verified"], False)
        self.assertTrue(any(reason in value for value in report["blockers"]), report)
        for name, relative in self.paths.items():
            contents = stamps[name].encode("utf-8")
            self.assertEqual(report["identities"][relative], {
                "sha256": hashlib.sha256(contents).hexdigest(), "size_bytes": len(contents),
            })
        self.write_stamps(self.good)
        return report

    def test_complete_records_pass_without_executing_the_inert_outputs(self):
        report = self.inspect()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertIs(report["native_flags_verified"], True)
        self.assertEqual(len(report["identities"]), 6)

    def test_each_required_macro_is_required_in_every_compiler_record(self):
        for role in COMPILER_ROLES:
            for flag in REQUIRED:
                with self.subTest(role=role, flag=flag):
                    self.assertRejected(self.changed(role, lambda line: line.replace(flag, "")),
                                        "frozen native RV64 configuration")

    def test_configuration_cannot_be_assembled_from_distinct_demo_records(self):
        stamps = dict(self.good)
        lines = stamps["demo"].split("\n")
        lines[0] = lines[0].replace(REQUIRED[0], "")
        lines[1] = lines[1].replace(REQUIRED[1], "")
        stamps["demo"] = "\n".join(lines)
        self.assertRejected(stamps, "demo kernel stamp")

    def test_other_records_cannot_supply_the_hosts_missing_macro(self):
        self.assertRejected(self.changed("host", lambda line: line.replace(REQUIRED[0], "")),
                            "demo host stamp")

    def test_include_and_dependency_operands_cannot_supply_required_macros(self):
        for role in COMPILER_ROLES:
            for operand in ("-I ", "-isystem ", "-MF ", "--include-directory="):
                for flag in REQUIRED:
                    with self.subTest(role=role, operand=operand, flag=flag):
                        self.assertRejected(self.changed(
                            role, lambda line: line.replace(flag, operand + flag)),
                            "frozen native RV64 configuration")

    def test_forwarded_include_operands_cannot_supply_required_macros(self):
        for role in COMPILER_ROLES:
            for transport in ("-Wp,-I,", "-Xpreprocessor -I -Xpreprocessor "):
                for flag in (REQUIRED[0], REQUIRED[-2]):
                    with self.subTest(role=role, transport=transport, flag=flag):
                        self.assertRejected(self.changed(
                            role, lambda line: line.replace(flag, transport + flag)),
                            "frozen native RV64 configuration")

    def test_each_kernel_architecture_selection_is_required_directly(self):
        for flag in ("-march=rv64imafd", "-mabi=lp64d"):
            for replacement in ("", "-I " + flag, "-Wp,-I," + flag,
                                "-Xpreprocessor -I -Xpreprocessor " + flag):
                with self.subTest(flag=flag, replacement=replacement):
                    self.assertRejected(self.changed(
                        "kernel", lambda line: line.replace(flag, replacement)), "kernel ISA/ABI")

    def test_wrong_repeated_and_forwarded_kernel_architecture_is_rejected(self):
        cases = (
            ("-march=rv64imafd", "-march=rv32imaf"),
            ("-mabi=lp64d", "-mabi=ilp32f"),
            ("-march=rv64imafd", "-march=rv64imafd -march=rv64imafd"),
            ("-mabi=lp64d", "-mabi=lp64d -mabi=lp64d"),
            ("-march=rv64imafd", "-march=rv64imafd -march=rv32imaf"),
            ("-march=rv64imafd", "-Wp,-march=rv64imafd"),
            ("-mabi=lp64d", "-Xpreprocessor -mabi=lp64d"),
        )
        for flag, replacement in cases:
            with self.subTest(replacement=replacement):
                self.assertRejected(self.changed(
                    "kernel", lambda line: line.replace(flag, replacement)), "kernel ISA/ABI")

    def test_linker_record_must_bind_only_the_generated_runtime(self):
        for replacement, reason in (
            ("-L/other/runtime -lvortex", "frozen runtime binding"),
            ("-L" + str(self.build / "sw/runtime") + " -lother", "unsupported compiler flags"),
            (self.good["demo"].split("\n")[2] + " -L/other/runtime", "frozen runtime binding"),
            ("-lvortex -L" + str(self.build / "sw/runtime"), "frozen runtime binding"),
        ):
            with self.subTest(linker=replacement):
                self.assertRejected(self.changed("linker", lambda _line: replacement), reason)

    def test_record_count_and_order_cannot_be_replaced_by_aggregate_flags(self):
        lines = self.good["demo"].splitlines()
        variants = (
            (" ".join(lines) + "\n", "kernel, host, and linker records"),
            ("\n".join(lines[:2]) + "\n", "kernel, host, and linker records"),
            (self.good["demo"] + lines[1] + "\n", "kernel, host, and linker records"),
            ("\n".join((lines[1], lines[0], lines[2])) + "\n", "kernel ISA/ABI"),
        )
        for demo, reason in variants:
            with self.subTest(demo=demo):
                self.assertRejected({**self.good, "demo": demo}, reason)
        self.assertRejected({**self.good, "runtime": self.good["runtime"] * 2},
                            "one compiler record")

    def test_glob_characters_are_rejected_even_as_quoted_or_escaped_literals(self):
        for role in COMPILER_ROLES:
            for character in "*?[]":
                for suffix in ("-I" + character, "'-I" + character + "'", "-I\\" + character):
                    with self.subTest(role=role, suffix=suffix):
                        self.assertRejected(self.changed(role, lambda line: line + " " + suffix),
                                            "shell expansion")

    def test_glob_matching_filename_cannot_change_the_inspected_argument_boundaries(self):
        write_file(self.build / "-I", b"INERT MATCH\n")
        for role in COMPILER_ROLES:
            with self.subTest(role=role):
                self.assertRejected(self.changed(
                    role, lambda line: line.replace(REQUIRED[0], "-I* " + REQUIRED[0])),
                    "shell expansion")

    def test_opaque_response_and_verilator_transports_are_rejected_in_every_role(self):
        for role in COMPILER_ROLES:
            for suffix in ("@unretained.rsp", "-CFLAGS '-DNOTE=1'", "--CFLAGS=-DNOTE=1",
                           "-MAKEFLAGS OPT_FAST=-O3", "--cc", "unretained.cpp"):
                with self.subTest(role=role, suffix=suffix):
                    self.assertRejected(self.changed(role, lambda line: line + " " + suffix),
                                        "unsupported compiler flags or source operands")

    def test_non_lf_line_separators_cannot_create_compilation_records(self):
        lines = self.good["demo"].splitlines()
        for separator in ("\r", "\r\n", "\v", "\f", "\x85", "\u2028", "\u2029"):
            with self.subTest(separator=repr(separator)):
                self.assertRejected({**self.good, "demo": separator.join(lines) + "\n"},
                                    "control characters or record separators")

    def test_controls_cannot_change_the_meaning_of_a_compiler_record(self):
        for role in COMPILER_ROLES:
            for character in ("\x00", "\x01", "\x1b", "\x7f", "\x9f", "\u00a0"):
                with self.subTest(role=role, character=repr(character)):
                    self.assertRejected(self.changed(role, lambda line: line + character),
                                        "control characters or record separators")

    def test_ordinary_quoted_and_split_definitions_remain_supported(self):
        stamps = {}
        for name, contents in self.good.items():
            lines = []
            for line in contents.splitlines():
                lines.append(" ".join(
                    "-D '" + word[2:] + "'" if word.startswith("-D") else "'" + word + "'"
                    for word in line.split()))
            stamps[name] = "\n".join(lines) + "\n"
        self.write_stamps(stamps)
        self.assertEqual(self.inspect()["outcome"], "pass")

    def test_valid_forwarded_macro_forms_remain_supported(self):
        for role in COMPILER_ROLES:
            for transport in ("-Wp,", "-Xpreprocessor "):
                with self.subTest(role=role, transport=transport):
                    self.write_stamps(self.changed(
                        role, lambda line: line.replace(REQUIRED[0], transport + REQUIRED[0])))
                    self.assertEqual(self.inspect()["outcome"], "pass")

    def test_utf8_decode_failure_preserves_original_byte_identity(self):
        relative = self.paths["runtime"]
        contents = self.good["runtime"].encode("utf-8") + b"\xff"
        write_file(self.build / relative, contents)
        report = self.inspect()
        self.assertEqual(report["outcome"], "blocked")
        self.assertIs(report["native_flags_verified"], False)
        self.assertEqual(report["identities"][relative], {
            "sha256": hashlib.sha256(contents).hexdigest(), "size_bytes": len(contents),
        })


if __name__ == "__main__":
    unittest.main()
