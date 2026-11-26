# SPDX-License-Identifier: Apache-2.0
"""Execute the required CI gate against complete and incomplete job outcomes."""

from itertools import product
import os
from pathlib import Path
import subprocess
import unittest

from test_p05_ci_workflow import children, scalars, script, steps, workflow


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/ci.yml"
RESULT_NAMES = ("PLAN_RESULT", "SETUP_RESULT", "BUILD_RESULT", "TESTS_RESULT")


class RequiredCIResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        jobs = children(workflow(WORKFLOW), "jobs", 2)
        cls.job = children(jobs, "complete", 4)
        gates = [step for step in steps(cls.job)
                 if step.get("name", (None,))[0] == "Gate"]
        if len(gates) != 1:
            raise AssertionError("expected exactly one required CI gate")
        cls.gate = gates[0]
        cls.gate_script = script(cls.gate)

    def environment(self, should_run):
        downstream = "success" if should_run else "skipped"
        return {
            "PLAN_RESULT": "success", "PLAN_RUN": str(should_run).lower(),
            "SETUP_RESULT": downstream, "BUILD_RESULT": downstream,
            "TESTS_RESULT": downstream,
        }

    def run_gate(self, values):
        environment = {"PATH": os.defpath, "LC_ALL": "C", **values}
        return subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-c", self.gate_script],
            cwd=ROOT, env=environment, text=True, capture_output=True, timeout=5,
        )

    def assert_gate(self, values, succeeds):
        result = self.run_gate(values)
        self.assertEqual(result.returncode == 0, succeeds,
                         (values, result.returncode, result.stdout, result.stderr))

    def test_complete_always_waits_for_all_required_jobs_without_suppressing_failure(self):
        self.assertEqual(self.job["needs"], ("[plan, setup, build, tests]", []))
        self.assertEqual(self.job["if"], ("always()", []))
        self.assertNotIn("continue-on-error", self.job)
        self.assertEqual(self.gate["shell"], ("bash", []))
        self.assertNotIn("if", self.gate)
        self.assertNotIn("continue-on-error", self.gate)

    def test_gate_environment_reads_the_required_results_and_plan_output(self):
        self.assertEqual(scalars(children(self.gate, "env", 10)), {
            "PLAN_RESULT": "${{ needs.plan.result }}",
            "PLAN_RUN": "${{ needs.plan.outputs.run }}",
            "SETUP_RESULT": "${{ needs.setup.result }}",
            "BUILD_RESULT": "${{ needs.build.result }}",
            "TESTS_RESULT": "${{ needs.tests.result }}",
        })

    def test_successful_planned_execution_passes(self):
        self.assert_gate(self.environment(True), True)

    def test_successful_plan_with_no_test_cells_passes(self):
        self.assert_gate(self.environment(False), True)

    def test_every_documented_result_combination_obeys_the_completion_policy(self):
        for should_run in (True, False):
            required_downstream = "success" if should_run else "skipped"
            for results in product(("success", "failure", "cancelled", "skipped"), repeat=4):
                with self.subTest(should_run=should_run, results=results):
                    values = self.environment(should_run)
                    values.update(zip(RESULT_NAMES, results))
                    plan, *downstream = results
                    expected = plan == "success" and all(
                        result == required_downstream for result in downstream)
                    self.assert_gate(values, expected)

    def test_missing_empty_or_unknown_required_results_fail_closed(self):
        for should_run in (True, False):
            for name, invalid in product(RESULT_NAMES, (None, "", "unknown", "Success", "*")):
                with self.subTest(should_run=should_run, name=name, invalid=invalid):
                    values = self.environment(should_run)
                    if invalid is None:
                        del values[name]
                    else:
                        values[name] = invalid
                    self.assert_gate(values, False)

    def test_missing_or_malformed_plan_output_fails_closed(self):
        invalid_outputs = (
            None, "", "True", "False", "TRUE", "FALSE", "1", "0", "null", "[]",
            " true", "false ", "true\n", "false\n", "true:false", "true; exit 0", "*",
        )
        for should_run, invalid in product((True, False), invalid_outputs):
            with self.subTest(should_run=should_run, invalid=invalid):
                values = self.environment(should_run)
                if invalid is None:
                    del values["PLAN_RUN"]
                else:
                    values["PLAN_RUN"] = invalid
                self.assert_gate(values, False)


if __name__ == "__main__":
    unittest.main()
