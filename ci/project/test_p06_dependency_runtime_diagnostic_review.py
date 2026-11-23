# SPDX-License-Identifier: Apache-2.0
"""Account exact native side outputs without treating diagnostics as evidence.

The dependency/native fixture is synthetic. These tests exercise the real
control readers and archive boundary; they execute no retained native code.
"""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import p06_dependency_control_replay as replay
from test_p06_dependency_control_replay import SyntheticControls, SyntheticNativeWithControlTools
from test_p06_dependency_native_replay import descriptor, digest


class RuntimeDiagnosticReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = SyntheticNativeWithControlTools()
        cls.native = cls.original.reader()
        cls.native.run()

    def setUp(self):
        self.packet = SyntheticControls(self.original, self.native)

    def selected(self, which):
        prefix = "work/" if which == "substitution" else ""
        return getattr(self.packet, which + "_files"), prefix + replay.RUNTIME_DIAGNOSTIC_NAME

    def check_zip(self, which, *, mutate_report=None):
        getattr(self.packet, "finish_" + which)()
        files, _ = self.selected(which)
        if mutate_report is not None:
            report = getattr(self.packet, which + "_report")
            mutate_report(report)
            pin = self.packet.put_json(files, "report.json", report)["sha256"]
            setattr(self.packet, which + "_pin", pin)
        with tempfile.TemporaryDirectory(prefix="p06-runtime-diagnostic-review-") as directory:
            path = Path(directory) / "control.zip"
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, body in sorted(files.items()):
                    archive.writestr(name, body)
            with self.native.api.ArchiveReader(path, digest(path.read_bytes())) as archive:
                return getattr(replay, "verify_" + which + "_view")(archive.view(""), native=self.native,
                    expected_report_sha256=getattr(self.packet, which + "_pin"),
                    expected_native_report_sha256=self.packet.native_pin)

    def test_exact_diagnostics_are_accounted_as_uninterpreted_bytes(self):
        for which in ("probe", "substitution"):
            with self.subTest(which=which):
                files, name = self.selected(which)
                self.assertIn(b".nan", files[name])
                result = self.check_zip(which)
                diagnostic = result["runtime_diagnostic"]
                self.assertEqual({key: diagnostic[key] for key in ("path", "sha256", "size_bytes")},
                                 descriptor(name, files[name]))
                for flag in ("interpreted", "numerical_evidence", "performance_evidence", "qualification_evidence"):
                    self.assertIs(diagnostic[flag], False)
                self.assertEqual(result["retained_files_checked"], len(files))
                self.assertTrue(all(result[flag] is False for flag in replay.contract.FALSE_CLAIMS))
                self.assertIs(result["managed_population_included"], False)
                self.assertIs(result["retained_code_executed"], False)

    def test_missing_diagnostic_is_rejected_even_with_rebound_inventory(self):
        for which in ("probe", "substitution"):
            with self.subTest(which=which):
                self.packet = SyntheticControls(self.original, self.native)
                files, name = self.selected(which)
                del files[name]
                with self.assertRaisesRegex(ValueError, "required Ramulator runtime diagnostic is absent"):
                    self.check_zip(which)

    def test_empty_diagnostic_is_rejected_even_with_rebound_inventory(self):
        for which in ("probe", "substitution"):
            with self.subTest(which=which):
                self.packet = SyntheticControls(self.original, self.native)
                files, name = self.selected(which)
                files[name] = b""
                with self.assertRaisesRegex(ValueError, "runtime diagnostic is empty"):
                    self.check_zip(which)

    def test_oversized_diagnostic_is_rejected_at_the_log_byte_bound(self):
        for which in ("probe", "substitution"):
            with self.subTest(which=which):
                self.packet = SyntheticControls(self.original, self.native)
                files, name = self.selected(which)
                files[name] = b"x" * (replay.contract.BUDGET["max_log_bytes"] + 1)
                with self.assertRaises(ValueError):
                    self.check_zip(which)

    def test_unknown_extra_members_remain_rejected(self):
        for which in ("probe", "substitution"):
            for extra in ("other.stats.log", "tmp/ramulator.stats.log"):
                with self.subTest(which=which, extra=extra):
                    self.packet = SyntheticControls(self.original, self.native)
                    files, _ = self.selected(which)
                    files[extra] = b"unexpected diagnostic\n"
                    with self.assertRaisesRegex(ValueError, "inventory"):
                        self.check_zip(which)

    def test_substitution_diagnostic_is_absent_from_both_frozen_snapshots(self):
        files, name = self.selected("substitution")
        row = descriptor(name, files[name])
        for key in ("control_products_before", "control_products_after"):
            self.assertNotIn(row, self.packet.substitution_report[key])
        self.assertEqual(self.check_zip("substitution")["outcome"], "pass")
        for key in ("control_products_before", "control_products_after"):
            with self.subTest(key=key):
                self.packet = SyntheticControls(self.original, self.native)
                self.packet.substitution_report[key] = sorted(
                    [*deepcopy(self.packet.substitution_report[key]), row], key=lambda value: value["path"])
                with self.assertRaisesRegex(ValueError, "substitution " + key):
                    self.check_zip("substitution")

    def test_final_substitution_diagnostic_identity_is_not_ignored(self):
        _, name = self.selected("substitution")

        def mutate(report):
            next(row for row in report["retained_files"] if row["path"] == name)["sha256"] = "0" * 64

        with self.assertRaisesRegex(ValueError, "substitution complete retained inventory"):
            self.check_zip("substitution", mutate_report=mutate)

    def test_runtime_output_requires_bound_native_destructor_source(self):
        original = self.native.source_body

        def source(name):
            if name == replay.RUNTIME_DIAGNOSTIC_SOURCE:
                return original(name).replace(b'nullstream("ramulator.stats.log")', b'nullstream("other.log")')
            return original(name)

        with mock.patch.object(self.native, "source_body", side_effect=source):
            with self.assertRaisesRegex(ValueError, "destructor side-output source differs"):
                self.check_zip("probe")


if __name__ == "__main__":
    unittest.main()
