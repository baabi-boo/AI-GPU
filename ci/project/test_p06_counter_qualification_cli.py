# SPDX-License-Identifier: Apache-2.0
"""Exercise the real qualification CLI without allowing descendant execution."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "ci/project/p06_counter_qualification_execute.py"
FALSE_FIELDS = (
    "native_preflight_passed", "native_lifetime_passed",
    "dependency_source_to_loaded_binary_verified", "counter_qualification_passed",
    "qualified", "ready_for_warm", "warm_execution", "full_warm_coverage",
    "acceptance_claimed", "phase_acceptance", "performance_acceptance",
)
AUDIT_PREFIX = "QUALIFICATION_CLI_AUDIT="
GUARDED_ENTRY = """
import json, runpy, sys
entry, *arguments = sys.argv[1:]
sys.path.insert(0, str(__import__('pathlib').Path(entry).parent))
events = []
def audit(event, args):
    if event in {'subprocess.Popen', 'os.system', 'os.posix_spawn',
                 'os.fork', 'os.forkpty', 'os.exec', 'socket.connect',
                 'socket.bind', 'socket.getaddrinfo'}:
        events.append(event)
        raise AssertionError('CLI attempted prohibited process/network operation: ' + event)
sys.addaudithook(audit)
sys.argv = [entry, *arguments]
try:
    runpy.run_path(entry, run_name='__main__')
finally:
    print('QUALIFICATION_CLI_AUDIT=' + json.dumps(events), file=sys.stderr)
"""


class QualificationCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="qualification-cli-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.tools = self.root / "tools"
        self.tools.mkdir()
        self.work = self.root / "work"
        self.output = self.root / "output"

    def arguments(self):
        return ["run", "--source-dir", str(ROOT), "--tools-dir", str(self.tools),
            "--work-dir", str(self.work), "--output-dir", str(self.output),
            "--expected-revision", "a" * 40,
            "--dependency-receipt", str(self.root / "dependency.json"),
            "--dependency-receipt-sha256", "b" * 64,
            "--counter-qualification", str(self.root / "proof.json"),
            "--counter-qualification-sha256", "c" * 64,
            "--diagnostic-archive", str(self.root / "diagnostic.zip"),
            "--diagnostic-archive-sha256", "d" * 64,
            "--control-archive", str(self.root / "controls.zip"),
            "--control-archive-sha256", "e" * 64]

    def invoke(self, arguments):
        result = subprocess.run([sys.executable, "-I", "-B", "-c", GUARDED_ENTRY,
            str(ENTRY), *arguments], cwd=ROOT, text=True, capture_output=True,
            timeout=30, check=False)
        audit = [line for line in result.stderr.splitlines() if line.startswith(AUDIT_PREFIX)]
        self.assertEqual(len(audit), 1, result.stderr)
        self.assertEqual(json.loads(audit[0][len(AUDIT_PREFIX):]), [], result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        return result

    def assert_blocked(self, result):
        self.assertEqual(result.returncode, 1, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["outcome"], "blocked")
        for name in FALSE_FIELDS:
            self.assertIs(summary[name], False, name)
        return summary

    def test_real_help_exposes_explicit_inputs_without_creating_outputs(self):
        result = self.invoke(["--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        for option in ("--counter-qualification", "--counter-qualification-sha256",
                "--diagnostic-archive", "--control-archive", "--jobs {1,2}"):
            self.assertIn(option, result.stdout)
        self.assertFalse(self.work.exists())
        self.assertFalse(self.output.exists())

    def test_real_invalid_mode_and_budget_exit_before_path_intake(self):
        cases = (("mode", "replay"), ("--jobs", "3"),
                 ("--timeout-seconds", "1801"), ("--run-timeout-seconds", "181"))
        for option, value in cases:
            with self.subTest(option=option):
                args = self.arguments()
                if option == "mode":
                    args[0] = value
                else:
                    args.extend((option, value))
                result = self.invoke(args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertIn("error:", result.stderr)
                self.assertFalse(self.work.exists())
                self.assertFalse(self.output.exists())

    def test_real_path_rejection_preserves_existing_outputs_and_aliases(self):
        sentinel = self.root / "existing-output"
        sentinel.mkdir()
        (sentinel / "sentinel").write_bytes(b"keep original bytes")
        alias = self.root / "tool-alias"
        alias.symlink_to(self.tools, target_is_directory=True)
        cases = (("--output-dir", sentinel, "fresh"),
                 ("--tools-dir", alias, "symlink"),
                 ("--source-dir", self.root, "selected source checkout"))
        for option, value, reason in cases:
            with self.subTest(option=option):
                args = self.arguments()
                args[args.index(option) + 1] = str(value)
                summary = self.assert_blocked(self.invoke(args))
                self.assertIn(reason, summary["reason"])
                self.assertFalse(self.work.exists())
                self.assertFalse(self.output.exists())
                self.assertEqual((sentinel / "sentinel").read_bytes(), b"keep original bytes")
                self.assertEqual(sorted(path.name for path in sentinel.iterdir()), ["sentinel"])
                self.assertTrue(alias.is_symlink())

    def test_real_invalid_revision_retains_a_zero_command_blocked_report(self):
        args = self.arguments()
        args[args.index("--expected-revision") + 1] = "master"
        summary = self.assert_blocked(self.invoke(args))
        self.assertIn("exact lowercase expected source revision", summary["reason"])
        report = json.loads((self.output / "report.json").read_text())
        self.assertEqual(report["commands"], [])
        self.assertEqual(report["processes"], [])
        self.assertEqual(report["native_execution"], "not_run")
        self.assertEqual(report["state"], "finished")
        self.assertEqual(report["completed_counts"], dict.fromkeys(report["expected_counts"], 0))
        for name in FALSE_FIELDS:
            self.assertIs(report[name], False, name)
        self.assertFalse(self.work.exists())


if __name__ == "__main__":
    unittest.main()
