# SPDX-License-Identifier: Apache-2.0
"""Independent checks of the local runner's actual CLI and failure boundaries."""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import p06_dependency_contract as contract
import p06_dependency_local_execute as execute
import test_p06_dependency_local_execute as fixtures


class LocalExecutionReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LocalExecutionTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def run_with(self, child):
        with mock.patch.object(execute, "run_bounded", side_effect=child):
            result = execute.execute(self.fixture.args)
        self.assertTrue(all(result[name] is False for name in contract.FALSE_CLAIMS))
        return result

    def test_each_stage_argv_is_accepted_by_its_real_parser_in_a_fresh_process(self):
        root = Path(__file__).resolve().parents[2]
        program = """
import argparse, importlib, json, sys
module = importlib.import_module(sys.argv[1])
original = argparse.ArgumentParser.parse_args
class Parsed(BaseException):
    pass
def parse(parser, args=None, namespace=None):
    original(parser, args, namespace)
    raise Parsed
argparse.ArgumentParser.parse_args = parse
try:
    module.main(json.loads(sys.argv[2]))
except Parsed:
    pass
else:
    raise AssertionError("CLI did not parse arguments")
"""
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                           PYTHONPATH=str(root / "ci/project"))
        rows = execute.stage_specs(self.fixture.paths, self.fixture.revision,
                                   sys.executable, "f" * 64)
        for row in rows:
            with self.subTest(stage=row["id"]):
                module = Path(row["argv"][2]).stem
                result = subprocess.run(
                    [sys.executable, "-B", "-c", program, module,
                     json.dumps(row["argv"][3:])],
                    cwd=root, env=environment, capture_output=True, text=True,
                    timeout=10, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_successful_child_with_incomplete_cleanup_stops_the_route(self):
        def child(*args, **kwargs):
            result = self.fixture.child(*args, **kwargs)
            result["cleanup_complete"] = False
            return result
        result = self.run_with(child)
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(len(result["stages"]), 1)
        self.assertFalse(result["stages"][0]["cleanup_complete"])
        self.assertEqual(result["native_execution"], "not_run")
        self.assertFalse(result["fresh_dependency_build_passed"])

    def test_native_stage_that_never_started_preserves_not_run(self):
        def child(argv, cwd, environment, log, **limits):
            if log.stem == "native-lifetime":
                return {"process_started": False, "outcome": "blocked",
                        "exit_code": None, "reason": "disk_reserve",
                        "cleanup_complete": True}
            return self.fixture.child(argv, cwd, environment, log, **limits)
        result = self.run_with(child)
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(len(result["stages"]), 3)
        self.assertEqual(result["native_execution"], "not_run")
        self.assertIn("disk_reserve", result["reason"])

    def test_changed_interpreter_stops_before_the_next_stage(self):
        def child(*args, **kwargs):
            result = self.fixture.child(*args, **kwargs)
            self.fixture.interpreter["sha256"] = "f" * 64
            return result
        result = self.run_with(child)
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(len(result["stages"]), 1)
        self.assertIn("interpreter changed", result["reason"])

    def test_child_report_hardlink_is_rejected_before_next_stage(self):
        def child(*args, **kwargs):
            result = self.fixture.child(*args, **kwargs)
            preparation = self.fixture.workspace / "evidence/dependency-preparation.json"
            os.link(preparation, self.fixture.workspace / "preparation-alias.json")
            return result
        result = self.run_with(child)
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(len(result["stages"]), 1)
        self.assertIn("bounded regular file", result["reason"])
        self.assertEqual(result["native_execution"], "not_run")


if __name__ == "__main__":
    unittest.main()
