# SPDX-License-Identifier: Apache-2.0
"""CLI-only controls; synthetic replay results do not certify an original."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import p06_dependency_contract as contract
import p06_dependency_control_replay as controls
import p06_dependency_native_replay as native
import p06_dependency_replay as dependency


REVISION = "a" * 40
PINS = {
    "sha256": "0" * 64,
    "dependency-receipt-sha256": "1" * 64,
    "native-report-sha256": "2" * 64,
    "source-manifest-sha256": "3" * 64,
    "probe-report-sha256": "4" * 64,
    "substitution-report-sha256": "5" * 64,
}


class NativeControlCliReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p06-reader-cli-review-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.archive = self.root / "selected-original.zip"
        self.archive.write_bytes(b"sentinel selected original; no semantic replay in this fixture")

    def arguments(self, module, output):
        args = (["--archive", str(self.archive), "--source-revision", REVISION]
                if module is native else [str(self.archive), "--expected-revision", REVISION])
        names = list(PINS)[:4] if module is native else list(PINS)
        for name in names:
            args.extend(("--" + name, PINS[name]))
        return [*args, "--prefix", "original", "--output", str(output)]

    def assert_no_execution(self, result):
        self.assertEqual(result["native_execution"], "not_run")
        self.assertIs(result["retained_code_executed"], False)
        for name in contract.FALSE_CLAIMS:
            self.assertIs(result[name], False)

    def synthetic_result(self):
        return {"scope": "synthetic-cli-boundary-only", "outcome": "pass",
            "retained_consistency": True, "native_execution": "not_run",
            "retained_code_executed": False, "synthetic_replay_boundary": True,
            **dict.fromkeys(contract.FALSE_CLAIMS, False)}

    def test_success_output_preserves_all_pins_and_explicit_inert_summary(self):
        for module in (native, controls):
            with self.subTest(module=module.__name__):
                output = self.root / (module.__name__ + ".json")
                result = self.synthetic_result()
                printed = io.StringIO()
                with mock.patch.object(module, "replay_archive", return_value=result) as replay, \
                        mock.patch("subprocess.Popen", side_effect=AssertionError("CLI started a process")), \
                        redirect_stdout(printed):
                    self.assertEqual(module.main(self.arguments(module, output)), 0)
                expected = {"expected_revision": REVISION,
                    "expected_receipt_sha256": PINS["dependency-receipt-sha256"],
                    "expected_native_report_sha256": PINS["native-report-sha256"],
                    "expected_source_manifest_sha256": PINS["source-manifest-sha256"],
                    "prefix": "original"}
                if module is controls:
                    expected.update(expected_probe_report_sha256=PINS["probe-report-sha256"],
                        expected_substitution_report_sha256=PINS["substitution-report-sha256"])
                replay.assert_called_once_with(self.archive, PINS["sha256"], **expected)
                self.assertEqual(json.loads(output.read_text()), result)
                summary = json.loads(printed.getvalue())
                self.assertEqual(summary["outcome"], "pass")
                self.assertIs(summary["retained_consistency"], True)
                self.assert_no_execution(summary)

    def test_existing_file_archive_alias_and_symlinks_are_never_overwritten(self):
        for module in (native, controls):
            for kind in ("regular", "archive", "archive-symlink", "dangling-symlink"):
                with self.subTest(module=module.__name__, kind=kind):
                    output = self.root / (module.__name__ + "-" + kind + ".json")
                    sentinel = b"existing review output must remain byte-for-byte"
                    dangling = self.root / (module.__name__ + "-absent-target")
                    if kind == "regular":
                        output.write_bytes(sentinel)
                    elif kind == "archive":
                        output = self.archive
                    elif kind == "archive-symlink":
                        output.symlink_to(self.archive)
                    else:
                        output.symlink_to(dangling)
                    archive_before = self.archive.read_bytes()
                    printed = io.StringIO()
                    with mock.patch.object(module, "replay_archive", return_value=self.synthetic_result()), \
                            redirect_stdout(printed):
                        self.assertEqual(module.main(self.arguments(module, output)), 1)
                    summary = json.loads(printed.getvalue())
                    self.assertEqual(summary["outcome"], "fail")
                    self.assertIs(summary["retained_consistency"], False)
                    self.assert_no_execution(summary)
                    self.assertEqual(self.archive.read_bytes(), archive_before)
                    if kind == "regular":
                        self.assertEqual(output.read_bytes(), sentinel)
                    elif "symlink" in kind:
                        self.assertTrue(output.is_symlink())
                    self.assertFalse(dangling.exists())

    def test_malformed_cli_pins_reject_before_archive_api_or_output_creation(self):
        for module, option in ((native, "--native-report-sha256"),
                               (controls, "--probe-report-sha256")):
            with self.subTest(module=module.__name__):
                output = self.root / (module.__name__ + "-bad-pin.json")
                args = self.arguments(module, output)
                args[args.index(option) + 1] = "not-an-external-digest"
                printed = io.StringIO()
                with mock.patch.object(dependency, "_archive_api",
                        side_effect=AssertionError("archive API reached before pin rejection")), \
                        mock.patch("subprocess.Popen", side_effect=AssertionError("CLI started a process")), \
                        redirect_stdout(printed):
                    self.assertEqual(module.main(args), 1)
                result = json.loads(printed.getvalue())
                self.assertIn("SHA-256", result["reason"])
                self.assertEqual(result["outcome"], "fail")
                self.assertIs(result["retained_consistency"], False)
                self.assert_no_execution(result)
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
