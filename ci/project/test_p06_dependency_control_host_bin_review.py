# SPDX-License-Identifier: Apache-2.0
"""Independent pending-control environment joins around a synthetic native context.

The existing fixture's dependency boundary is mocked. These tests exercise the
control reader's environment derivation, not an actual native execution.
"""

from copy import copy
from pathlib import PurePosixPath
import unittest

from test_p06_dependency_control_replay import SyntheticControls, SyntheticNativeWithControlTools


class PendingControlHostBinReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = SyntheticNativeWithControlTools()
        cls.context = cls.original.reader()
        cls.context.run()

    def setUp(self):
        self.native = copy(self.context)
        self.native.paths = dict(self.context.paths)
        self.packet = SyntheticControls(self.original, self.native)
        self.default_path = self.packet.probe_report["environment"]["PATH"]

    def select_host(self, value):
        # The selected native context is an input to this control reader. Its
        # compiler can still come from a fallback directory on the selected PATH.
        self.native.paths["host_bin"] = PurePosixPath(value) if value is not None else None
        entries = ([value] if value is not None else [])
        entries += [str(PurePosixPath(self.native.tools["executing_python"]["path"]).parent),
                    "/usr/bin", "/bin"]
        return ":".join(dict.fromkeys(entries))

    def test_default_probe_path_remains_exact(self):
        self.assertEqual(self.select_host(None), self.default_path)
        self.assertEqual(self.packet.probe_check()["outcome"], "pass")
        self.packet.probe_report["environment"]["PATH"] = "/foreign/bin:" + self.default_path
        with self.assertRaisesRegex(ValueError, "pending environment"):
            self.packet.probe_check()

    def test_explicit_host_bin_matches_producer_environment(self):
        expected = self.select_host("/local-host/bin")
        self.packet.probe_report["environment"]["PATH"] = expected
        result = self.packet.probe_check()
        self.assertEqual(result["outcome"], "pass")
        self.assertIs(result["managed_population_included"], False)
        self.assertEqual(result["native_execution"], "not_run")

    def test_explicit_host_bin_cannot_be_omitted_or_substituted(self):
        expected = self.select_host("/local-host/bin")
        for value in (self.default_path, "/foreign/bin:" + self.default_path,
                      "/local-host/bin:" + expected, self.default_path + ":/local-host/bin"):
            self.packet.probe_report["environment"]["PATH"] = value
            with self.subTest(path=value), self.assertRaisesRegex(ValueError, "pending environment"):
                self.packet.probe_check()

    def test_duplicate_path_entries_are_folded_in_producer_order(self):
        expected = self.select_host("/usr/bin")
        self.assertEqual(expected.split(":").count("/usr/bin"), 1)
        self.packet.probe_report["environment"]["PATH"] = expected
        self.assertEqual(self.packet.probe_check()["outcome"], "pass")

    def test_substitution_keeps_its_independent_default_path(self):
        self.select_host("/local-host/bin")
        self.assertEqual(self.packet.substitution_report["environment"]["PATH"], self.default_path)
        self.assertEqual(self.packet.substitution_check()["outcome"], "pass")


if __name__ == "__main__":
    unittest.main()
