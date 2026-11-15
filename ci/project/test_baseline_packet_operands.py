# SPDX-License-Identifier: Apache-2.0
"""Compiler operands cannot supply frozen macros in inert packet fixtures."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from baseline_packet import verify_packet
from baseline_packet_contract import _stamp
from baseline_packet_fixture import make_packet, refresh_stamp, save_report
from baseline_packet_io import PacketError


REQUIRED = "-DVX_CFG_EXT_TCU_ENABLE"


class PacketOperandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "packet"
        self.report = make_packet(self.root)
        self.cases = {case["id"]: case
                      for case in json.loads((self.root / "matrix.json").read_text())["cases"]}

    def verify(self):
        save_report(self.root, self.report)
        return verify_packet(self.root, require_native_pass=True)

    def assertNativePass(self):
        result = self.verify()
        self.assertEqual(result["outcome"], "pass")
        self.assertIs(result["native_matrix_passed"], True)
        self.assertIs(result["phase_complete"], False)

    def reject_each_role(self, payloads, reason="frozen configuration"):
        for role, artifact in enumerate(self.report["cases"][0]["configuration_artifacts"]):
            original = (self.root / artifact["path"]).read_text()
            for payload in payloads:
                with self.subTest(role=role, flags=payload):
                    refresh_stamp(self.root, artifact, original.replace(REQUIRED, payload))
                    try:
                        with self.assertRaisesRegex(PacketError, reason):
                            self.verify()
                    finally:
                        refresh_stamp(self.root, artifact, original)

    def test_gcc_operands_cannot_impersonate_required_defines_in_any_role(self):
        self.reject_each_role(tuple(option + " " + REQUIRED for option in (
            "-I", "-isystem", "-iquote", "-idirafter", "-MF", "-MT", "-MQ", "-o",
            "-iprefix", "-iwithprefix", "-iwithprefixbefore", "-isysroot", "-imultilib",
            "-imultiarch", "-L", "-l", "-x", "-Xassembler", "-Xlinker",
        )))

    def test_quoted_operands_are_not_reparsed_as_flags(self):
        self.reject_each_role((
            '-I "' + REQUIRED + '"', "-I\t'" + REQUIRED + "'",
            "-isystem '-D VX_CFG_EXT_TCU_ENABLE'",
            "-I '-Wp," + REQUIRED + "'",
            "-MF '-Xpreprocessor " + REQUIRED + "'",
            "-MQ '-CFLAGS " + REQUIRED + "'",
        ))

    def test_long_gcc_option_operands_are_consumed(self):
        self.reject_each_role(tuple(option + " " + REQUIRED for option in (
            "--include-directory", "--include-directory-after", "--include-prefix",
            "--include-with-prefix", "--include-with-prefix-after",
            "--include-with-prefix-before", "--sysroot", "--output", "--library-directory",
        )))

    def test_observed_verilator_options_consume_operands_with_either_dash_form(self):
        self.reject_each_role(tuple(dash + option + " " + REQUIRED
                                    for dash in ("-", "--") for option in (
                                        "language", "replication-limit", "top-module",
                                        "x-assign", "x-initial", "j")))

    def test_positional_option_names_cannot_hide_an_undefinition(self):
        self.reject_each_role(tuple(REQUIRED + " " + name + " -UVX_CFG_EXT_TCU_ENABLE"
                                    for name in ("language", "top-module", "x-assign", "j")),
                              "undefines a required configuration macro")

    def test_preprocessor_transports_preserve_operand_arity(self):
        self.reject_each_role(tuple(payload for option in ("-I", "-isystem", "-MF", "-MT", "-MQ")
                                    for payload in (
                                        "-Wp," + option + "," + REQUIRED,
                                        "-Xpreprocessor " + option + " -Xpreprocessor " + REQUIRED,
                                    )))

    def test_preprocessor_dependency_options_take_a_filename(self):
        self.reject_each_role(tuple(payload for option in ("-MD", "-MMD") for payload in (
            "-Wp," + option + "," + REQUIRED,
            "-Xpreprocessor " + option + " -Xpreprocessor " + REQUIRED,
        )))

    def test_compiler_transports_preserve_operand_arity(self):
        self.reject_each_role((
            "-CFLAGS '-I " + REQUIRED + "'",
            '--CFLAGS="-isystem ' + REQUIRED + '"',
            "-CFLAGS -I -CFLAGS " + REQUIRED,
            "-CFLAGS '-Wp,-I," + REQUIRED + "'",
            "-CFLAGS '-Xpreprocessor -I -Xpreprocessor " + REQUIRED + "'",
        ))

    def test_unknown_or_ambiguous_options_fail_closed(self):
        self.reject_each_role(tuple(option + " " + REQUIRED for option in (
            "-v", "-y", "-Wfuture", "--threads", "-output-split", "-lib-create",
            "-libmap", "-LDFLAGS", "--LDFLAGS", "--future1", "-future1",
            "--include-direct", "--unrecognized-option", "--", "-CFLAGS -CFLAGS",
        )), "opaque|unsupported")

    def test_incomplete_transports_cannot_consume_a_parent_argument(self):
        self.reject_each_role((
            "-Xpreprocessor -I " + REQUIRED,
            "-CFLAGS -I " + REQUIRED,
            "-CFLAGS '-Xpreprocessor -I' " + REQUIRED,
        ), "without an operand")

    def test_full_fixture_rejects_all_eighteen_swallowed_definitions(self):
        for case in self.report["cases"]:
            for artifact in case["configuration_artifacts"]:
                original = (self.root / artifact["path"]).read_text()
                rewritten = original.replace(REQUIRED, "-I " + REQUIRED)
                refresh_stamp(self.root, artifact, rewritten)
                with self.subTest(case=case["id"], stamp=artifact["path"]):
                    with self.assertRaisesRegex(PacketError, "frozen configuration"):
                        _stamp(rewritten.encode(), self.cases[case["id"]], "synthetic stamp")
        with self.assertRaisesRegex(PacketError, "frozen configuration"):
            self.verify()

    def test_split_and_joined_paths_preserve_all_eighteen_valid_stamps(self):
        controls = (
            '-I "$SOURCE/include with spaces" -I$BUILD/include -isystem $TOOLS/include '
            '-iquote "$SOURCE/quoted headers" -idirafter $SOURCE/after -MF $OUTPUT/deps.d '
            '-MT kernel.o -MQ "kernel target.o" -o $OUTPUT/kernel.o '
            '--include-directory=$SOURCE/headers --output=$OUTPUT/alternate.o '
            '-I -DVX_CFG_TCU_TYPE_DPI -MF -UVX_CFG_EXT_TCU_ENABLE '
            '-Wp,-I,$SOURCE/headers -Xpreprocessor -iquote -Xpreprocessor $SOURCE/headers '
            "-CFLAGS '-I $SOURCE/headers -D UNRELATED_DIAGNOSTIC=1'\n"
        )
        for case in self.report["cases"]:
            for artifact in case["configuration_artifacts"]:
                original = (self.root / artifact["path"]).read_text()
                refresh_stamp(self.root, artifact, original + controls)
        self.assertNativePass()

    def test_supported_macro_transports_remain_valid_after_operand_consumption(self):
        controls = (
            "-I -Xpreprocessor " + REQUIRED,
            "-MD -MMD " + REQUIRED,
            "-CFLAGS -I -CFLAGS $SOURCE/include -CFLAGS '-D VX_CFG_EXT_TCU_ENABLE'",
            "-Wp,-I,$SOURCE/include,-D,VX_CFG_EXT_TCU_ENABLE",
            "-Xpreprocessor -I -Xpreprocessor $SOURCE/include "
            "-Xpreprocessor -D -Xpreprocessor VX_CFG_EXT_TCU_ENABLE",
        )
        for artifact in self.report["cases"][0]["configuration_artifacts"]:
            original = (self.root / artifact["path"]).read_text()
            for payload in controls:
                with self.subTest(stamp=artifact["path"], flags=payload):
                    refresh_stamp(self.root, artifact, original.replace(REQUIRED, payload))
                    self.assertNativePass()
            refresh_stamp(self.root, artifact, original)

    def test_operand_checks_never_open_paths_or_execute_text(self):
        case = self.report["cases"][0]
        artifact = case["configuration_artifacts"][0]
        original = (self.root / artifact["path"]).read_bytes()
        case = self.cases[case["id"]]
        with mock.patch("builtins.open", side_effect=AssertionError("external file open")), \
                mock.patch("os.open", side_effect=AssertionError("external file open")), \
                mock.patch("subprocess.Popen", side_effect=AssertionError("process execution")), \
                mock.patch("os.system", side_effect=AssertionError("shell execution")):
            _stamp(original + b"-I /unretained/include -MF /unretained/deps.d\n", case, "inert stamp")
            for payload in (b"-I @unretained.rsp", b"-I '$(touch forbidden)'", b"-o `id`"):
                with self.subTest(flags=payload):
                    with self.assertRaises(PacketError):
                        _stamp(original + payload + b"\n", case, "inert stamp")


if __name__ == "__main__":
    unittest.main()
