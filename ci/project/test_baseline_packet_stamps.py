# SPDX-License-Identifier: Apache-2.0
"""Adversarial retained-flag tests using inert packets, never GPU evidence."""

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from baseline_packet import verify_packet
from baseline_packet_contract import _stamp
from baseline_packet_fixture import make_packet, refresh_stamp, save_report
from baseline_packet_io import PacketError


class PacketStampTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "packet"
        self.report = make_packet(self.root)

    def verify(self):
        save_report(self.root, self.report)
        return verify_packet(self.root, require_native_pass=True)

    def assertNativePass(self):
        result = self.verify()
        self.assertEqual(result["outcome"], "pass")
        self.assertIs(result["native_matrix_passed"], True)
        self.assertIs(result["phase_complete"], False)

    def reject_each_role(self, payloads, reason, *, case_index=0):
        # Change retained bytes AND their recorded identity: a stale hash must
        # not be the reason these contradictory compiler flags are rejected.
        for role, artifact in enumerate(self.report["cases"][case_index]["configuration_artifacts"]):
            original = (self.root / artifact["path"]).read_bytes()
            for payload in payloads:
                with self.subTest(case=case_index, role=role, flags=payload):
                    refresh_stamp(self.root, artifact,
                                  original + ("CXXFLAGS: " + payload + "\n").encode("utf-8"))
                    try:
                        with self.assertRaisesRegex(PacketError, reason):
                            self.verify()
                    finally:
                        refresh_stamp(self.root, artifact, original)

    def test_split_and_quoted_protected_undefinitions_are_rejected_in_every_role(self):
        self.reject_each_role((
            "-UVX_CFG_EXT_TCU_ENABLE", "-U VX_CFG_EXT_TCU_ENABLE",
            '-U"VX_CFG_EXT_TCU_ENABLE"', '"-UVX_CFG_EXT_TCU_ENABLE"',
            "-U 'VX_CFG_EXT_TCU_ENABLE'", "-U\tVX_CFG_EXT_TCU_ENABLE",
            "-U ITYPE -D ITYPE=bf16", "-U VX_CFG_NUM_THREADS -D VX_CFG_NUM_THREADS=16",
            "--undefine-macro=VX_CFG_EXT_TCU_ENABLE",
        ), "undefines a required configuration macro")

    def test_precision_and_geometry_conflicts_are_rejected_in_every_role(self):
        self.reject_each_role((
            "-D ITYPE=bf16", '-D"ITYPE=bf16"', "'-DITYPE=bf16'",
            "-D 'OTYPE=fp16'", "-D VX_CFG_NUM_THREADS=16",
            '-D"VX_CFG_XLEN=32"', "--define-macro=ITYPE=bf16",
            "-D VX_CFG_EXT_TCU_ENABLE=", "-D VX_CFG_EXT_TCU_ENABLE=0",
        ), "conflicting defines")

    def test_nonnative_selectors_are_rejected_in_every_role(self):
        self.reject_each_role((
            "-D VX_CFG_TCU_TYPE_DPI", '-D"VX_CFG_TCU_TYPE_DPI"',
            "'-DVX_CFG_TCU_TYPE_DPI'", "-D VX_CFG_FPU_TYPE_DPI",
            '-D"VX_CFG_FPU_TYPE_DPI=0"',
        ), "selects non-native arithmetic")
        self.reject_each_role((
            "-D VX_CFG_TCU_TYPE=DPI", '-D"VX_CFG_FPU_TYPE=DPI"',
        ), "conflicting defines")

    def test_attention_undefinitions_and_tile_conflicts_are_rejected_in_every_role(self):
        self.reject_each_role(("-U WGMMA_RS", '-U"WGMMA_NRC"', "-U OTYPE"),
                              "undefines a required configuration macro", case_index=4)
        self.reject_each_role(("-D WGMMA_NRC=16", '-D"ITYPE=fp16"'),
                              "conflicting defines", case_index=4)

    def test_transported_macro_overrides_are_rejected_in_every_role(self):
        self.reject_each_role((
            "-Wp,-U,VX_CFG_EXT_TCU_ENABLE",
            "-Xpreprocessor -U -Xpreprocessor VX_CFG_EXT_TCU_ENABLE",
            "-Xpreprocessor -UVX_CFG_EXT_TCU_ENABLE",
            "-CFLAGS '-U VX_CFG_EXT_TCU_ENABLE'",
            '--CFLAGS="-U VX_CFG_EXT_TCU_ENABLE"',
        ), "undefines a required configuration macro")
        self.reject_each_role((
            "-Wp,-D,ITYPE=bf16", "-Xpreprocessor -D -Xpreprocessor ITYPE=bf16",
            "-CFLAGS '-D ITYPE=bf16'", '-CFLAGS="-DITYPE=bf16"',
        ), "conflicting defines")
        self.reject_each_role((
            "-Wp,-DVX_CFG_TCU_TYPE_DPI",
            "-Xpreprocessor -D -Xpreprocessor VX_CFG_TCU_TYPE_DPI",
            "-CFLAGS '-D VX_CFG_TCU_TYPE_DPI'",
        ), "selects non-native arithmetic")

    def test_opaque_flag_sources_are_rejected_in_every_role(self):
        self.reject_each_role((
            "@unretained.rsp", '"@unretained.rsp"', "-Wp,@unretained.rsp",
            "-Xpreprocessor @unretained.rsp", "-CFLAGS '@unretained.rsp'",
            "-include unretained.h", "-imacros unretained.h",
            "-specs=unretained.specs", "--config=unretained.cfg",
            "-f unretained.f", "-F unretained.f", "-funretained.f", "-Funretained.f",
            "-Xclang -UVX_CFG_EXT_TCU_ENABLE",
            "-Xcompiler=-UVX_CFG_EXT_TCU_ENABLE",
            "-wrapper unretained-wrapper",
            "+define+VX_CFG_TCU_TYPE_DPI", "+undefineall",
            "-MAKEFLAGS 'CXXFLAGS=-UVX_CFG_EXT_TCU_ENABLE'",
            "-MAKEFLAGS 'OPT_FAST=-O2 -UVX_CFG_EXT_TCU_ENABLE'",
        ), "opaque")

    def test_malformed_flag_syntax_is_rejected_in_every_role(self):
        self.reject_each_role((
            "-D", "-U", "-D=1", '-D "ITYPE=bf16', "-U ITYPE=fp16",
            "-D 'VX_CFG_EXT_TCU_ENABLE(x)=1'", "-CFLAGS", "-Wp,",
        ), "malformed|without an operand|empty preprocessor")
        self.reject_each_role(("-DITYPE=fp16#ignored",), "inline comment")

    def test_all_six_cases_accept_equivalent_joined_split_and_quoted_definitions(self):
        forms = (
            lambda word: "-D " + word[2:],
            lambda word: '-D"' + word[2:] + '"',
            lambda word: "'" + word + "'",
            lambda word: '"-D" "' + word[2:] + '"',
        )
        originals = [(artifact, (self.root / artifact["path"]).read_text())
                     for case in self.report["cases"]
                     for artifact in case["configuration_artifacts"]]
        for form_index, form in enumerate(forms):
            with self.subTest(form=form_index):
                for artifact, original in originals:
                    rewritten = "\n".join(
                        " ".join(form(word) if word.startswith("-D") else word
                                 for word in line.split())
                        for line in original.splitlines()) + "\n"
                    refresh_stamp(self.root, artifact, rewritten)
                self.assertNativePass()

    def test_same_effective_definitions_and_safe_transports_remain_valid(self):
        for artifact in self.report["cases"][0]["configuration_artifacts"]:
            original = (self.root / artifact["path"]).read_text()
            refresh_stamp(self.root, artifact, original + (
                'CXXFLAGS: -D ITYPE=fp16 -D"ITYPE=fp16" -D VX_CFG_TCU_TYPE=TFR '
                "-D VX_CFG_EXT_TCU_ENABLE=1 -D VX_CFG_TCU_TYPE_TFR=1 "
                "-U UNRELATED_DIAGNOSTIC -D UNRELATED_DIAGNOSTIC=1 "
                "-Wp,-D,ITYPE=fp16 -Xpreprocessor -D -Xpreprocessor OTYPE=fp32 "
                "-CFLAGS '-D VX_CFG_FPU_TYPE=STD' "
                "-MAKEFLAGS OPT_FAST=-O2 -MAKEFLAGS OPT_GLOBAL=-O2\n"
            ))
        self.assertNativePass()

    def test_missing_equals_means_one_but_an_explicit_empty_value_does_not(self):
        for role, artifact in enumerate(self.report["cases"][0]["configuration_artifacts"]):
            original = (self.root / artifact["path"]).read_text()
            with self.subTest(role=role):
                refresh_stamp(self.root, artifact, original.replace(
                    "-DVX_CFG_EXT_TCU_ENABLE", "-DVX_CFG_EXT_TCU_ENABLE=1"))
                self.assertNativePass()
                refresh_stamp(self.root, artifact, original.replace(
                    "-DVX_CFG_EXT_TCU_ENABLE", "-DVX_CFG_EXT_TCU_ENABLE="))
                with self.assertRaisesRegex(PacketError, "frozen configuration"):
                    self.verify()
                refresh_stamp(self.root, artifact, original)

    def test_parser_never_executes_expansions_or_opens_external_option_sources(self):
        case = self.report["cases"][0]
        artifact = case["configuration_artifacts"][0]
        original = (self.root / artifact["path"]).read_bytes()
        with mock.patch("builtins.open", side_effect=AssertionError("external file open")), \
                mock.patch("os.open", side_effect=AssertionError("external file open")), \
                mock.patch("os.system", side_effect=AssertionError("shell execution")), \
                mock.patch("subprocess.Popen", side_effect=AssertionError("process execution")):
            for flags in (b"@unretained.rsp", b"-include unretained.h",
                          b'-CFLAGS "$(touch should-not-exist)"', b"`printf -UVX_CFG_EXT_TCU_ENABLE`"):
                with self.subTest(flags=flags):
                    with self.assertRaises(PacketError):
                        _stamp(original + flags + b"\n", case, "inert stamp")


if __name__ == "__main__":
    unittest.main()
