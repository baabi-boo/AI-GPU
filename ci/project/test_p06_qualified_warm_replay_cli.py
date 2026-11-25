# SPDX-License-Identifier: Apache-2.0
"""Exercise direct replay entry and its trusted-source failure boundaries."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

import p06_qualified_warm_replay as replay


ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "ci/project/p06_qualified_warm_replay.py"


class QualifiedWarmReplayCliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="qualified-warm-replay-cli-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.archive = self.directory / "original.zip"
        self.output = self.directory / "result.json"

    def invoke(self, arguments, *, cwd=ROOT, entry=ENTRY, env=None):
        return subprocess.run([sys.executable, "-B", str(entry), *arguments],
            cwd=cwd, env=env, text=True, capture_output=True, timeout=30, check=False)

    def arguments(self, digest="a" * 64):
        return ["--archive", str(self.archive), "--sha256", digest,
            "--source-revision", "a" * 40, "--dependency-receipt-sha256", "a" * 64,
            "--native-report-sha256", "a" * 64, "--source-manifest-sha256", "a" * 64,
            "--counter-qualification-sha256", replay.contract.SOURCE_PROOF_SHA256,
            "--diagnostic-archive", str(self.directory / "diagnostic.zip"),
            "--diagnostic-archive-sha256", "a" * 64,
            "--control-archive", str(self.directory / "control.zip"),
            "--control-archive-sha256", "a" * 64, "--output", str(self.output)]

    def assert_help(self, result):
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertIn("usage:", result.stdout)
        for option in ("--archive", "--source-revision", "--dependency-receipt-sha256",
                "--native-report-sha256", "--source-manifest-sha256",
                "--counter-qualification-sha256", "--diagnostic-archive-sha256",
                "--control-archive-sha256", "--output"):
            self.assertIn(option, result.stdout)

    def assert_failure(self, result, reason):
        self.assertEqual((result.returncode, result.stderr), (1, ""))
        summary = json.loads(result.stdout)
        self.assertEqual(summary["outcome"], "fail")
        self.assertEqual(summary["reason"], reason)
        self.assertEqual(summary["native_execution"], "not_run")
        for name in ("counter_qualification_passed", "qualified_warm_passed",
                     "retained_code_executed", *replay.contract.FALSE_CLAIMS):
            self.assertIs(summary[name], False, name)
        self.assertFalse(self.output.exists())

    def test_direct_help_from_repository_root(self):
        self.assert_help(self.invoke(["--help"], entry=ENTRY.relative_to(ROOT)))

    def test_direct_help_from_unrelated_directory(self):
        self.assert_help(self.invoke(["--help"], cwd=self.directory))
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_direct_malformed_archive_pins_return_normal_failure_json(self):
        for digest in ("invalid", "A" * 64, "a" * 63):
            with self.subTest(digest=digest):
                self.assert_failure(self.invoke(self.arguments(digest)),
                    "exact external local qualification ZIP SHA-256 is required")
        self.assertFalse(self.archive.exists())

    def test_direct_malformed_external_pins_return_normal_failure_json(self):
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("dependency-build/report.json", b"{}\n")
            archive.writestr("qualified-warm/report.json", b"{}\n")
        original = self.archive.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        cases = (("--dependency-receipt-sha256", "dependency receipt"),
                 ("--native-report-sha256", "native report"),
                 ("--source-manifest-sha256", "native source manifest"),
                 ("--counter-qualification-sha256", "qualification proof"),
                 ("--diagnostic-archive-sha256", "diagnostic original"),
                 ("--control-archive-sha256", "control original"),
                 ("--source-revision", None))
        for option, label in cases:
            with self.subTest(option=option):
                arguments = self.arguments(digest)
                arguments[arguments.index(option) + 1] = "invalid"
                reason = ("exact external source revision is required" if label is None
                          else "exact external " + label + " SHA-256 is required")
                self.assert_failure(self.invoke(arguments, cwd=self.directory), reason)
                self.assertEqual(self.archive.read_bytes(), original)

    def test_direct_reader_copied_outside_checkout_fails_closed(self):
        entry = self.directory / "checkout/ci/project/p06_qualified_warm_replay.py"
        entry.parent.mkdir(parents=True)
        entry.write_bytes(ENTRY.read_bytes())
        environment = dict(os.environ, PYTHONPATH=str(ENTRY.parent))
        result = self.invoke(["--help"], entry=entry, cwd=self.directory, env=environment)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("qualified warm reader loaded outside the trusted checkout", result.stderr)


class QualifiedWarmReplaySourceBindingTests(unittest.TestCase):
    def test_inventory_binds_exact_reader_paths_and_bytes(self):
        rows = {row["path"]: row for row in replay._reader_sources()}
        for name in ("p06_qualified_warm_records", "p06_qualified_warm_analyze",
                     "p06_qualified_warm_replay"):
            path = "ci/project/" + name + ".py"
            body = (ROOT / path).read_bytes()
            self.assertEqual(rows[path], {"path": path,
                "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)})
        self.assertNotIn("ci/project/__main__.py", rows)

    def test_reader_and_helpers_reject_wrong_source_locations(self):
        with tempfile.TemporaryDirectory(prefix="qualified-warm-reader-location-") as directory:
            for module in (replay, replay.records, replay.analysis):
                with self.subTest(module=module.__name__):
                    foreign = Path(directory) / Path(module.__file__).name
                    foreign.write_bytes(Path(module.__file__).read_bytes())
                    with mock.patch.object(module, "__file__", str(foreign)):
                        with self.assertRaisesRegex(ValueError,
                                "qualified warm reader loaded outside the trusted checkout"):
                            replay._reader_sources()

    def test_changed_reader_bytes_reject_before_archive_intake(self):
        read_bytes = Path.read_bytes

        def changed_reader(path):
            body = read_bytes(path)
            return body + b"\n" if path == ENTRY else body

        with mock.patch.object(Path, "read_bytes", changed_reader):
            with self.assertRaisesRegex(ValueError, "trusted qualification reader changed after import"):
                replay.replay_archive(Path("/unopened-original.zip"), "a" * 64,
                    expected_revision="a" * 40, expected_receipt_sha256="a" * 64,
                    expected_native_report_sha256="a" * 64,
                    expected_source_manifest_sha256="a" * 64,
                    expected_qualification_sha256=replay.contract.SOURCE_PROOF_SHA256,
                    diagnostic_archive=Path("/unopened-diagnostic.zip"), diagnostic_sha256="a" * 64,
                    control_archive=Path("/unopened-control.zip"), control_sha256="a" * 64)


if __name__ == "__main__":
    unittest.main()
