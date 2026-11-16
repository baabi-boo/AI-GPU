# SPDX-License-Identifier: Apache-2.0
"""Exercise command dispatch, failure privacy, and nonexecution boundaries."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import hwemu


SOURCE = Path(__file__).resolve().parents[2]
CLI = SOURCE / "ci/project/hwemu.py"


def report(outcome="blocked"):
    result = {
        "schema_version": 1,
        "target": "hw_emu",
        "outcome": outcome,
        "input_consistency_verified": outcome == "planned",
        **hwemu.BOUNDARIES,
        "candidate": None,
        "blockers": ["synthetic prerequisite is absent"],
        "limitations": ["Synthetic CLI response; no vendor qualification."],
    }
    if outcome == "planned":
        result.update(candidate={"argv": ["./ci/blackbox.sh", "--driver=xrt",
                                          "--target=hw_emu", "--app=demo", "--args=-n1"],
                                 "inherit_environment": False,
                                 "supervision_required": True}, blockers=[])
    return result


class HwemuCommandTests(unittest.TestCase):
    def run_cli(self, *arguments):
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, str(CLI), *arguments], cwd=SOURCE,
            env=environment, capture_output=True, text=True,
            check=False, timeout=20,
        )

    def assert_blocked(self, result, secret=None):
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stderr, "")
        observed = json.loads(result.stdout)
        self.assertEqual(observed["outcome"], "blocked")
        for key, value in hwemu.BOUNDARIES.items():
            self.assertEqual(observed[key], value)
        self.assertIsNone(observed.get("candidate"))
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        if secret:
            self.assertNotIn(secret, result.stdout + result.stderr)
        return observed

    def test_help_exposes_only_read_only_commands(self):
        for arguments in (("--help",), ("inventory", "--help"), ("plan", "--help")):
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
        result = self.run_cli("--help")
        self.assertIn("{inventory,plan}", result.stdout)
        self.assertIn("never executes a GPU", " ".join(result.stdout.split()))

    def test_usage_errors_never_offer_execution_or_output_mutations(self):
        for arguments in ((), ("run",), ("execute",), ("install",), ("download",),
                          ("plan",), ("inventory", "--execute"),
                          ("inventory", "--output", "/private/output.json"),
                          ("inventory", "--roo", "/private/source")):
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertIn("use --help", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertNotIn("/private/", result.stderr)

    def test_usage_diagnostics_do_not_repeat_hostile_argument_text(self):
        secret = "private-token-$(touch-/tmp/unwanted)"
        result = self.run_cli(secret)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(secret, result.stdout + result.stderr)

    def test_missing_and_noncanonical_manifest_paths_are_redacted(self):
        for manifest in ("/missing-private-input/manifest.json", "relative-manifest.json",
                         "/private-input/../manifest.json", "/private-input/$SECRET.json"):
            with self.subTest(manifest=manifest):
                self.assert_blocked(self.run_cli("plan", manifest, "--json"), manifest)

    def test_malformed_duplicate_and_nonobject_json_remain_unchanged(self):
        contents = (b"{", b'{"a":1,"a":2}', b"[]", b'{"a":NaN}', b"\xff")
        with tempfile.TemporaryDirectory(prefix="ai-gpu-cli-") as temporary:
            path = Path(temporary) / "private-manifest.json"
            for data in contents:
                with self.subTest(data=data):
                    path.write_bytes(data)
                    before = path.stat().st_mtime_ns
                    self.assert_blocked(self.run_cli("plan", str(path), "--json"), str(path))
                    self.assertEqual(path.read_bytes(), data)
                    self.assertEqual(path.stat().st_mtime_ns, before)

    def test_oversized_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="ai-gpu-cli-") as temporary:
            path = Path(temporary) / "large-manifest.json"
            with path.open("wb") as stream:
                stream.truncate(256 * 1024 + 1)
            self.assert_blocked(self.run_cli("plan", str(path), "--json"), str(path))
            self.assertEqual(path.stat().st_size, 256 * 1024 + 1)

    def test_symlink_manifest_is_not_followed(self):
        with tempfile.TemporaryDirectory(prefix="ai-gpu-cli-") as temporary:
            original = Path(temporary) / "original.json"
            original.write_text("{}", encoding="utf-8")
            alias = Path(temporary) / "alias.json"
            alias.symlink_to(original)
            self.assert_blocked(self.run_cli("plan", str(alias), "--json"), str(alias))
            self.assertEqual(original.read_text(encoding="utf-8"), "{}")
            self.assertTrue(alias.is_symlink())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO checks require POSIX")
    def test_fifo_manifest_does_not_block_waiting_for_a_writer(self):
        with tempfile.TemporaryDirectory(prefix="ai-gpu-cli-") as temporary:
            path = Path(temporary) / "manifest-pipe"
            os.mkfifo(path)
            self.assert_blocked(self.run_cli("plan", str(path), "--json"), str(path))

    def test_actual_inventory_keeps_absent_source_blocked_and_private(self):
        root = "/missing-private-checkout-for-hwemu"
        observed = self.assert_blocked(self.run_cli("inventory", "--root", root, "--json"), root)
        self.assertTrue(observed["blockers"])
        self.assertIn("vendor_tools", observed)


class HwemuDispatchTests(unittest.TestCase):
    def invoke(self, arguments):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = hwemu.main(arguments)
        self.assertEqual(errors.getvalue(), "")
        return code, output.getvalue()

    def test_inventory_dispatch_never_calls_plan_or_reads_a_manifest(self):
        expected = report()
        with patch.object(hwemu, "inventory", return_value=expected) as inspect, \
                patch.object(hwemu, "read_manifest", side_effect=AssertionError("manifest read")), \
                patch.object(hwemu, "plan_manifest", side_effect=AssertionError("planned")), \
                patch("subprocess.Popen", side_effect=AssertionError("process started")), \
                patch("os.system", side_effect=AssertionError("shell started")):
            code, output = self.invoke(["inventory", "--root", "/example/source", "--json"])
        inspect.assert_called_once_with("/example/source")
        self.assertEqual(code, 1)
        self.assertEqual(output, json.dumps(expected, indent=2, sort_keys=True) + "\n")

    def test_candidate_plan_exits_zero_without_claiming_execution(self):
        expected = report("planned")
        data = {"synthetic": True}
        with patch.object(hwemu, "read_manifest", return_value=data) as read, \
                patch.object(hwemu, "plan_manifest", return_value=expected) as plan, \
                patch.object(hwemu, "inventory", side_effect=AssertionError("inventory")), \
                patch("subprocess.Popen", side_effect=AssertionError("process started")), \
                patch("os.system", side_effect=AssertionError("shell started")):
            code, output = self.invoke(["plan", "/example/manifest.json", "--json"])
        read.assert_called_once_with("/example/manifest.json")
        plan.assert_called_once_with(data)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output), expected)
        for key, value in hwemu.BOUNDARIES.items():
            self.assertEqual(json.loads(output)[key], value)

    def test_manifest_strings_are_data_and_inputs_are_not_modified(self):
        with tempfile.TemporaryDirectory(prefix="ai-gpu-cli-") as temporary:
            path = Path(temporary) / "manifest.json"
            data = b'{"synthetic_command":"$(touch /tmp/never-run); v++ --version"}'
            path.write_bytes(data)
            before = path.stat().st_mtime_ns
            with patch.object(hwemu, "plan_manifest", return_value=report()) as plan, \
                    patch("subprocess.Popen", side_effect=AssertionError("process started")), \
                    patch("os.system", side_effect=AssertionError("shell started")):
                code, _output = self.invoke(["plan", str(path), "--json"])
            self.assertEqual(code, 1)
            plan.assert_called_once_with(json.loads(data))
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual(path.stat().st_mtime_ns, before)

    def test_plan_input_error_does_not_reach_the_planner(self):
        with patch.object(hwemu, "read_manifest", side_effect=ValueError("private input path")), \
                patch.object(hwemu, "plan_manifest", side_effect=AssertionError("planned")):
            code, output = self.invoke(["plan", "/private/manifest.json", "--json"])
        self.assertEqual(code, 1)
        self.assertNotIn("private", output)
        self.assertIsNone(json.loads(output)["candidate"])

    def test_expected_backend_errors_are_redacted(self):
        for error in (ValueError, OSError, RuntimeError, TypeError):
            with self.subTest(error=error), \
                    patch.object(hwemu, "inventory", side_effect=error("private-token-and-path")):
                code, output = self.invoke(["inventory", "--json"])
                self.assertEqual(code, 1)
                self.assertNotIn("private-token-and-path", output)
                self.assertNotIn("Traceback", output)

    def test_upstream_claim_drift_is_rejected_instead_of_normalized_to_success(self):
        for key, invalid in (("execution_performed", True), ("phase_complete", True),
                             ("launch_ready", True), ("vendor_qualification_verified", True),
                             ("vendor_qualification", "qualified"),
                             ("acceptance_outcome", "pass"), ("acceptance_id", "P02-A01")):
            observed = report("planned")
            observed[key] = invalid
            with self.subTest(key=key), patch.object(hwemu, "read_manifest", return_value={}), \
                    patch.object(hwemu, "plan_manifest", return_value=observed):
                code, output = self.invoke(["plan", "/example/manifest.json", "--json"])
                self.assertEqual(code, 1)
                self.assertEqual(json.loads(output)["outcome"], "blocked")
                self.assertIsNone(json.loads(output)["candidate"])

    def test_incomplete_or_contradictory_reports_cannot_exit_zero(self):
        cases = []
        for outcome in ("pass", "ready", "complete"):
            value = report("planned")
            value["outcome"] = outcome
            cases.append(value)
        value = report("planned")
        value["blockers"] = ["still missing"]
        cases.append(value)
        value = report("planned")
        value["candidate"] = None
        cases.append(value)
        value = report("planned")
        del value["input_consistency_verified"]
        cases.append(value)
        value = report("planned")
        value["resources"] = {"available_memory_bytes": float("nan")}
        cases.append(value)
        value = report()
        value["candidate"] = {"argv": ["unexpected"]}
        cases.append(value)
        cases.extend((None, []))
        for observed in cases:
            with self.subTest(observed=observed), \
                    patch.object(hwemu, "read_manifest", return_value={}), \
                    patch.object(hwemu, "plan_manifest", return_value=observed):
                code, output = self.invoke(["plan", "/example/manifest.json", "--json"])
                self.assertEqual(code, 1)
                self.assertIsNone(json.loads(output)["candidate"])

    def test_inventory_cannot_return_a_planned_candidate(self):
        with patch.object(hwemu, "inventory", return_value=report("planned")):
            code, output = self.invoke(["inventory", "--json"])
        self.assertEqual(code, 1)
        self.assertIsNone(json.loads(output)["candidate"])

    def test_inventory_gets_consistent_boundary_fields_without_mutating_original(self):
        observed = report()
        for key in ("launch_ready", "vendor_qualification", "acceptance_id", "acceptance_outcome"):
            del observed[key]
        original = deepcopy(observed)
        with patch.object(hwemu, "inventory", return_value=observed):
            code, output = self.invoke(["inventory", "--json"])
        self.assertEqual(code, 1)
        for key, value in hwemu.BOUNDARIES.items():
            self.assertEqual(json.loads(output)[key], value)
        self.assertEqual(observed, original)

    def test_text_candidate_output_retains_no_execution_warning(self):
        with patch.object(hwemu, "read_manifest", return_value={}), \
                patch.object(hwemu, "plan_manifest", return_value=report("planned")):
            code, output = self.invoke(["plan", "/example/manifest.json"])
        self.assertEqual(code, 0)
        self.assertIn("No GPU execution performed; P01-A03 remains blocked.", output)
        self.assertIn("vendor qualification and bounded supervision remain required", output)
        self.assertIn('"--target=hw_emu"', output)


if __name__ == "__main__":
    unittest.main()
