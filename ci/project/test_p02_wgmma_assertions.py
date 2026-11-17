# SPDX-License-Identifier: Apache-2.0
"""Require active Verilator assertions in synthetic WGMMA compiler records."""

import unittest

import test_p02_wgmma_matrix as fixtures


class AssertionRecordTests(unittest.TestCase):
    def contexts(self):
        for variant in fixtures.MANIFEST["variants"]:
            yield variant, False
            if variant["sparse"]:
                yield variant, True

    def test_valid_rtl_records_require_no_change(self):
        for variant, witness in self.contexts():
            with self.subTest(variant=variant["id"], witness=witness):
                stamps = fixtures.compiler_fixture("rtlsim", variant, witness=witness)
                result = fixtures.check_compiler(stamps, "rtlsim", variant, witness=witness)
                self.assertEqual([row["role"] for row in result],
                                 ["runtime", "verilator", "backend_cpp", "kernel", "host"])

    def test_missing_assertion_switch_rejects(self):
        for variant, witness in self.contexts():
            with self.subTest(variant=variant["id"], witness=witness):
                stamps = fixtures.compiler_fixture("rtlsim", variant, witness=witness)
                stamps[1] = stamps[1].replace("--assert ", "", 1)
                with self.assertRaisesRegex(ValueError, "exactly one --assert"):
                    fixtures.check_compiler(stamps, "rtlsim", variant, witness=witness)

    def test_duplicate_assertion_switch_rejects(self):
        for variant, witness in self.contexts():
            with self.subTest(variant=variant["id"], witness=witness):
                stamps = fixtures.compiler_fixture("rtlsim", variant, witness=witness)
                stamps[1] = stamps[1].replace("--assert ", "--assert --assert ", 1)
                with self.assertRaisesRegex(ValueError, "exactly one --assert"):
                    fixtures.check_compiler(stamps, "rtlsim", variant, witness=witness)

    def test_malformed_or_disabled_assertion_switch_rejects(self):
        replacements = ("--assert=1", "--assert=0", "-assert", "--no-assert", "--assert --no-assert")
        for variant, witness in self.contexts():
            for replacement in replacements:
                with self.subTest(variant=variant["id"], witness=witness, replacement=replacement):
                    stamps = fixtures.compiler_fixture("rtlsim", variant, witness=witness)
                    stamps[1] = stamps[1].replace("--assert ", replacement + " ", 1)
                    with self.assertRaises(ValueError):
                        fixtures.check_compiler(stamps, "rtlsim", variant, witness=witness)

    def test_simx_records_do_not_require_a_verilator_switch(self):
        for variant in fixtures.MANIFEST["variants"]:
            with self.subTest(variant=variant["id"]):
                stamps = fixtures.compiler_fixture("simx", variant)
                self.assertNotIn("--assert", "\n".join(stamps))
                result = fixtures.check_compiler(stamps, "simx", variant)
                self.assertEqual([row["role"] for row in result],
                                 ["runtime", "backend_cpp", "kernel", "host"])


if __name__ == "__main__":
    unittest.main()
