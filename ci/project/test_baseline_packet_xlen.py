# SPDX-License-Identifier: Apache-2.0
"""Both effective RV64 macros are required in inert retained-stamp fixtures."""

from pathlib import Path
import tempfile
import unittest

from baseline_packet import verify_packet
from baseline_packet_fixture import make_packet, refresh_stamp, save_report
from baseline_packet_io import PacketError


NUMERIC_XLEN = "-DVX_CFG_XLEN=64"
RV64_SELECTOR = "-DVX_CFG_XLEN_64"


class PacketXlenTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "packet"
        self.report = make_packet(self.root)
        self.stamps = [(case["id"], artifact,
                        (self.root / artifact["path"]).read_text())
                       for case in self.report["cases"]
                       for artifact in case["configuration_artifacts"]]
        self.assertEqual(len(self.stamps), 18)
        for _, _, contents in self.stamps:
            self.assertEqual(contents.count(NUMERIC_XLEN), 1)
            self.assertEqual(contents.count(RV64_SELECTOR), 1)

    def verify(self):
        save_report(self.root, self.report)
        return verify_packet(self.root, require_native_pass=True)

    def assertNativePass(self):
        result = self.verify()
        self.assertEqual(result["outcome"], "pass")
        self.assertIs(result["native_matrix_passed"], True)
        self.assertIs(result["phase_complete"], False)

    def assertStampRejected(self, artifact, original, rewritten):
        # Refresh retained identities so rejection tests the effective flags.
        refresh_stamp(self.root, artifact, rewritten)
        try:
            with self.assertRaises(PacketError):
                self.verify()
        finally:
            refresh_stamp(self.root, artifact, original)

    def reject_each_role(self, payloads, *, target=RV64_SELECTOR, append=False):
        for _, artifact, original in self.stamps[:3]:
            for payload in payloads:
                with self.subTest(stamp=artifact["source"]["path"], flags=payload):
                    rewritten = (original + "CXXFLAGS: " + payload + "\n" if append
                                 else original.replace(target, payload))
                    self.assertStampRejected(artifact, original, rewritten)

    def test_fixture_has_both_effective_rv64_macros_in_all_eighteen_stamps(self):
        self.assertNativePass()

    def test_numeric_xlen_64_remains_required_with_a_valid_companion(self):
        self.reject_each_role((
            "", "-DVX_CFG_XLEN", "-DVX_CFG_XLEN=", "-DVX_CFG_XLEN=0",
            "-DVX_CFG_XLEN=32", "-DVX_CFG_XLEN=128", "-I " + NUMERIC_XLEN,
        ), target=NUMERIC_XLEN)

    def test_missing_companion_is_rejected_in_each_of_eighteen_stamps(self):
        for case_id, artifact, original in self.stamps:
            with self.subTest(case=case_id, stamp=artifact["source"]["path"]):
                self.assertStampRejected(artifact, original,
                                         original.replace(RV64_SELECTOR, ""))

    def test_companion_requires_effective_value_one_in_every_role(self):
        self.reject_each_role(tuple(RV64_SELECTOR + "=" + value for value in (
            "0", "", "2", "64", "true", "01", "1U", "-1",
        )))

    def test_conflicting_xlen_selectors_are_rejected_even_when_zero_or_empty(self):
        self.reject_each_role(tuple("-DVX_CFG_XLEN_" + selector + value
                                    for selector in ("32", "128", "064", "CUSTOM", "64_OTHER")
                                    for value in ("", "=0", "=1", "=")), append=True)

    def test_forwarded_conflicting_selectors_are_rejected_in_every_role(self):
        self.reject_each_role((
            "-D VX_CFG_XLEN_32=0", '-D"VX_CFG_XLEN_32=0"',
            "'-DVX_CFG_XLEN_32=0'", "--define-macro=VX_CFG_XLEN_32=0",
            "-Wp,-D,VX_CFG_XLEN_32=0",
            "-Xpreprocessor -D -Xpreprocessor VX_CFG_XLEN_32=0",
            "-CFLAGS '-D VX_CFG_XLEN_32=0'", '--CFLAGS="-DVX_CFG_XLEN_32=0"',
        ), append=True)

    def test_companion_undefinitions_are_rejected_in_every_role(self):
        self.reject_each_role((
            "-UVX_CFG_XLEN_64", "-U VX_CFG_XLEN_64", '-U"VX_CFG_XLEN_64"',
            "-Wp,-U,VX_CFG_XLEN_64",
            "-Xpreprocessor -U -Xpreprocessor VX_CFG_XLEN_64",
            "-CFLAGS '-U VX_CFG_XLEN_64'",
        ), append=True)

    def test_compiler_operands_cannot_supply_the_companion_in_any_role(self):
        self.reject_each_role(tuple(option + " " + RV64_SELECTOR for option in (
            "-I", "-isystem", "-iquote", "-idirafter", "-MF", "-MT", "-MQ", "-o",
            "--include-directory", "--output", "-top-module", "--language", "-j",
        )) + (
            '-I "' + RV64_SELECTOR + '"',
            "-isystem '-D VX_CFG_XLEN_64=1'",
        ))

    def test_forwarded_operands_cannot_supply_the_companion_in_any_role(self):
        self.reject_each_role((
            "-Wp,-I," + RV64_SELECTOR,
            "-Wp,-MD," + RV64_SELECTOR,
            "-Xpreprocessor -I -Xpreprocessor " + RV64_SELECTOR,
            "-Xpreprocessor -MMD -Xpreprocessor " + RV64_SELECTOR,
            "-CFLAGS '-I " + RV64_SELECTOR + "'",
            '--CFLAGS="-isystem ' + RV64_SELECTOR + '"',
            "-CFLAGS -I -CFLAGS " + RV64_SELECTOR,
            "-CFLAGS '-Wp,-I," + RV64_SELECTOR + "'",
            "-CFLAGS '-Xpreprocessor -I -Xpreprocessor " + RV64_SELECTOR + "'",
        ))

    def test_swallowed_companion_is_rejected_in_each_of_eighteen_stamps(self):
        for case_id, artifact, original in self.stamps:
            with self.subTest(case=case_id, stamp=artifact["source"]["path"]):
                self.assertStampRejected(artifact, original,
                                         original.replace(RV64_SELECTOR, "-I " + RV64_SELECTOR))

    def test_full_packet_rejects_all_eighteen_swallowed_companions(self):
        for _, artifact, original in self.stamps:
            refresh_stamp(self.root, artifact,
                          original.replace(RV64_SELECTOR, "-I " + RV64_SELECTOR))
        with self.assertRaises(PacketError):
            self.verify()

    def test_genuine_split_quoted_and_forwarded_companions_remain_valid(self):
        forms = (
            RV64_SELECTOR, RV64_SELECTOR + "=1", "-D VX_CFG_XLEN_64=1",
            '-D"VX_CFG_XLEN_64"', "'-DVX_CFG_XLEN_64=1'",
            '"-D" "VX_CFG_XLEN_64=1"',
            "--define-macro=VX_CFG_XLEN_64=1", "--define-macro VX_CFG_XLEN_64",
            "-Wp,-DVX_CFG_XLEN_64", "-Wp,-D,VX_CFG_XLEN_64=1",
            "-Xpreprocessor -DVX_CFG_XLEN_64=1",
            "-Xpreprocessor -D -Xpreprocessor VX_CFG_XLEN_64",
            "-CFLAGS '-D VX_CFG_XLEN_64=1'", '--CFLAGS="-DVX_CFG_XLEN_64"',
            "-CFLAGS -D -CFLAGS VX_CFG_XLEN_64",
            "-CFLAGS '-Wp,-D,VX_CFG_XLEN_64=1'",
            "-CFLAGS '-Xpreprocessor -D -Xpreprocessor VX_CFG_XLEN_64'",
        )
        for payload in forms:
            with self.subTest(flags=payload):
                for _, artifact, original in self.stamps:
                    refresh_stamp(self.root, artifact, original.replace(RV64_SELECTOR, payload))
                self.assertNativePass()

    def test_repeated_equivalent_companions_remain_valid(self):
        for _, artifact, original in self.stamps:
            refresh_stamp(self.root, artifact, original + (
                "CXXFLAGS: -D VX_CFG_XLEN_64=1 -Wp,-DVX_CFG_XLEN_64 "
                "-CFLAGS '-D VX_CFG_XLEN_64=1'\n"
            ))
        self.assertNativePass()

    def test_xlen_looking_operands_do_not_create_effective_selector_conflicts(self):
        for _, artifact, original in self.stamps:
            refresh_stamp(self.root, artifact, original + (
                "CXXFLAGS: -I -DVX_CFG_XLEN_32=0 -MF -UVX_CFG_XLEN_64 "
                "-Wp,-I,-DVX_CFG_XLEN_128 -Xpreprocessor -MQ "
                "-Xpreprocessor -DVX_CFG_XLEN_32=1 "
                "-CFLAGS '-I -DVX_CFG_XLEN_64=0'\n"
            ))
        self.assertNativePass()


if __name__ == "__main__":
    unittest.main()
