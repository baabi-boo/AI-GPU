"""Independent scratch probes of failed-attempt preservation at ac2f2ae7."""
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, "/workspace/ai-gpu-next/ci/project")
import p06_dependency_local_execute as execute
import p06_dependency_local_prepare as prepare
import test_p06_dependency_local_execute as execution_fixtures
import test_p06_dependency_local_prepare as preparation_fixtures

HOST_TOOLS = prepare._host_tools


class FailurePreservationReview(unittest.TestCase):
    def fixture(self, kind):
        cls = (execution_fixtures.LocalExecutionTests if kind == "execution"
               else preparation_fixtures.LocalPreparationExecutionTests)
        fixture = cls(methodName="runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_partial_extraction_is_retained_and_retry_preserves_original(self):
        f = self.fixture("preparation")
        marker = f.workspace / "tools" / "partial-member"
        def partial(*_):
            marker.parent.mkdir()
            marker.write_bytes(b"partial archive member retained")
            raise ValueError("deliberate interrupted extraction")
        f.mocks["provision"].side_effect = partial
        result = f.run_prepare()
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["native_execution"], "not_run")
        receipt = f.workspace / "evidence/dependency-preparation.json"
        original = receipt.read_bytes()
        with self.assertRaisesRegex(ValueError, "receipt already exists"):
            prepare.prepare(f.args)
        self.assertEqual(receipt.read_bytes(), original)
        self.assertEqual(marker.read_bytes(), b"partial archive member retained")

    def test_missing_host_compiler_retains_blocked_attempt_before_extraction(self):
        f = self.fixture("preparation")
        f.mocks["tools"].side_effect = HOST_TOOLS
        with mock.patch.object(prepare.shutil, "which", return_value=None):
            result = f.run_prepare()
        self.assertEqual(result["outcome"], "blocked")
        self.assertEqual(result["native_execution"], "not_run")
        self.assertIn("required local host tool is absent", result["reason"])
        f.mocks["provision"].assert_not_called()
        self.assertFalse((f.workspace / "tools").exists())

    def test_symlinked_execution_workspace_parent_has_no_outside_write(self):
        f = self.fixture("execution")
        outside = f.root / "outside"
        outside.mkdir()
        alias = f.root / "alias"
        alias.symlink_to(outside, target_is_directory=True)
        f.args.workspace_dir = alias / "attempt"
        with self.assertRaisesRegex(ValueError, "without symlink traversal"):
            execute.execute(f.args)
        self.assertEqual(list(outside.iterdir()), [])

    def test_symlinked_preparation_evidence_directory_has_no_outside_write(self):
        f = self.fixture("preparation")
        outside = f.root / "outside"
        outside.mkdir()
        marker = outside / "marker"
        marker.write_bytes(b"preserve")
        (f.workspace / "evidence").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "evidence must be canonical"):
            prepare.prepare(f.args)
        self.assertEqual(marker.read_bytes(), b"preserve")
        self.assertEqual([p.name for p in outside.iterdir()], ["marker"])

    def test_symlinked_existing_preparation_receipt_is_never_replaced(self):
        f = self.fixture("preparation")
        marker = f.root / "outside-original.json"
        marker.write_bytes(b"preserve original")
        evidence = f.workspace / "evidence"
        evidence.mkdir()
        target = evidence / "dependency-preparation.json"
        target.symlink_to(marker)
        with self.assertRaisesRegex(ValueError, "receipt already exists"):
            prepare.prepare(f.args)
        self.assertEqual(marker.read_bytes(), b"preserve original")
        self.assertTrue(target.is_symlink())
        f.mocks["provision"].assert_not_called()

    def test_native_timeout_without_child_report_preserves_unknown_and_stops(self):
        f = self.fixture("execution")
        def child(argv, cwd, environment, log, **limits):
            if log.stem == "native-lifetime":
                return {"process_started": True, "outcome": "fail", "exit_code": -15,
                        "reason": "timeout", "cleanup_complete": True}
            return f.child(argv, cwd, environment, log, **limits)
        with mock.patch.object(execute, "run_bounded", side_effect=child):
            result = execute.execute(f.args)
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["native_execution"], "unknown")
        self.assertEqual(len(result["stages"]), 3)
        self.assertEqual(set(result["reports"]), {"preparation", "dependency-build"})
        receipt = f.workspace / "evidence/local-execution.json"
        original = receipt.read_bytes()
        self.assertEqual(json.loads(original), result)
        with self.assertRaisesRegex(ValueError, "must be fresh"):
            execute.execute(f.args)
        self.assertEqual(receipt.read_bytes(), original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
