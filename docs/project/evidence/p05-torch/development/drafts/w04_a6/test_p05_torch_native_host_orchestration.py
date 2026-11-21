# SPDX-License-Identifier: Apache-2.0
"""Failure retention for the optional host runner; no Torch or compiler required."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import p05_test_runtime
import p05_torch_native_host_tests as host


ROOT = Path(p05_test_runtime.__file__).resolve().parents[2]


class HostBoundaryRetentionTests(unittest.TestCase):
    def exercise(self, result):
        temporary = tempfile.TemporaryDirectory(prefix="p05-native-host-orchestration-")
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        runtime = mock.Mock()
        runtime.root = base
        runtime.extension = base / "test-extension"
        runtime.extension.write_bytes(b"ORCHESTRATION FIXTURE, NOT AN EXTENSION")
        runtime.bundle = base / "bundle"
        runtime.bundle.mkdir()
        (runtime.bundle / "manifest.json").write_text('{"scope":"orchestration-only"}\n')
        runtime.commands = ()
        runtime.environment.return_value = {"PYTHONPATH": "/host-only/orchestration-fixture"}
        output = base / "output"

        def existing_text_capture(*args, **kwargs):
            observed = host.subprocess.run([])
            return subprocess.CompletedProcess(
                observed.args, observed.returncode,
                observed.stdout.decode("utf-8").replace("\r\n", "\n"),
                observed.stderr.decode("utf-8").replace("\r\n", "\n"))

        runtime.run_python.side_effect = existing_text_capture
        process = {"side_effect": result} if isinstance(result, BaseException) or callable(result) else {"return_value": result}
        with mock.patch.object(p05_test_runtime, "build_test_runtime", return_value=runtime), \
                mock.patch.object(host.subprocess, "run", **process), \
                mock.patch.object(host.shutil, "disk_usage", return_value=mock.Mock(free=20 * 1024**3)), \
                mock.patch.object(sys, "path", list(sys.path)), \
                mock.patch.object(sys, "argv", [str(host.__file__), "--source-dir", str(ROOT),
                                               "--work-dir", str(output)]), \
                redirect_stdout(io.StringIO()):
            code = host.main()
        report = json.loads((output / "report.json").read_text())
        self.assertEqual(report["completed"], len(host.SCENARIOS))
        self.assertEqual(report["acceptance_claimed"], False)
        self.assertEqual(report["backend_execution"], "not_run")
        self.assertEqual(len(report["results"]), len(host.SCENARIOS))
        return code, report, output

    def assert_logs(self, output, stdout, stderr):
        for scenario in host.SCENARIOS:
            self.assertEqual((output / "children" / scenario / "stdout.log").read_bytes(), stdout)
            self.assertEqual((output / "children" / scenario / "stderr.log").read_bytes(), stderr)

    def test_valid_json_keeps_original_line_endings(self):
        order = iter(host.SCENARIOS)
        def payload(scenario):
            return (json.dumps({"scope": host.SCOPE, "scenario": scenario,
                                "format": "fp16", "outcome": "pass"}) + "\r\n").encode()
        def invoke(*args, **kwargs):
            return subprocess.CompletedProcess([], 0, payload(next(order)), b"")
        code, report, output = self.exercise(invoke)
        self.assertEqual(code, 0)
        self.assertEqual(report["outcome"], "pass")
        for scenario in host.SCENARIOS:
            self.assertEqual((output / "children" / scenario / "stdout.log").read_bytes(), payload(scenario))
            self.assertEqual((output / "children" / scenario / "stderr.log").read_bytes(), b"")

    def test_wrong_scope_scenario_format_or_outcome_cannot_pass(self):
        base = {"scope": host.SCOPE, "scenario": host.SCENARIOS[0], "format": "fp16", "outcome": "pass"}
        wrong = [{**base, key: value} for key, value in
                 (("scope", "simx"), ("scenario", "unknown"), ("format", "bf16"), ("outcome", "fail"))]
        for value in [*wrong, {}, []]:
            with self.subTest(value=value):
                stdout = json.dumps(value).encode()
                code, report, output = self.exercise(subprocess.CompletedProcess([], 0, stdout, b""))
                self.assertEqual(code, 1)
                self.assertTrue(all(row["outcome"] == "fail" and row["reason"] == "child observation identity differs"
                                    for row in report["results"]))
                self.assert_logs(output, stdout, b"")

    def test_malformed_or_nonutf8_json_is_failed_and_retained(self):
        for stdout in (b'noise\r\n{}\n', b'\xff\x00\r\n'):
            with self.subTest(stdout=stdout):
                code, report, output = self.exercise(subprocess.CompletedProcess([], 0, stdout, b""))
                self.assertEqual(code, 1)
                self.assertEqual(report["outcome"], "fail")
                self.assertTrue(all(row["reason"].startswith("invalid child JSON: ")
                                    and row["outcome"] == "fail" for row in report["results"]))
                self.assert_logs(output, stdout, b"")

    def test_timeout_keeps_partial_bytes_without_repr_conversion(self):
        stdout, stderr = b'partial\r\n\x00\xff', b'error\r\n\xff'
        error = subprocess.TimeoutExpired(["scripted-child"], 30, output=stdout, stderr=stderr)
        code, report, output = self.exercise(error)
        self.assertEqual(code, 1)
        self.assertTrue(all(row["reason"] == "30-second child timeout" for row in report["results"]))
        self.assert_logs(output, stdout, stderr)

    def test_nonzero_child_keeps_opaque_output_bytes(self):
        stdout, stderr = b'opaque\xff\r\n', b'problem\x00\r\n'
        code, report, output = self.exercise(subprocess.CompletedProcess([], 23, stdout, stderr))
        self.assertEqual(code, 1)
        self.assertTrue(all(row["exit_code"] == 23 and row["outcome"] == "fail"
                            for row in report["results"]))
        self.assert_logs(output, stdout, stderr)


if __name__ == "__main__":
    unittest.main()
