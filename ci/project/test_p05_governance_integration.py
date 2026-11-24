# SPDX-License-Identifier: Apache-2.0
"""Static P05 coverage checks for the existing full source governance suite.

These tests inspect workflow and runner source only; no compiler, package
installer, native loader, or accelerator qualification runs here.
"""

from pathlib import Path
import unittest

from governance_workflow_test_support import assert_strict_governance_step
from test_p04_ci_contract import positive_path_patterns
from test_p05_ci_workflow import children, path_filters, scalars, script, steps, workflow


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/project-governance.yml"
P05_PATHS = {
    ".github/workflows/p05-python.yml", "python/**", "setup.py", "pyproject.toml",
    "MANIFEST.in", "docs/designs/python_binding_v1.md",
}


class PythonGovernanceIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = workflow(WORKFLOW)
        cls.events = children(cls.workflow, "on", 2)
        cls.jobs = children(cls.workflow, "jobs", 2)
        cls.job = children(cls.jobs, "governance", 4)
        cls.steps = steps(cls.job)
        cls.lines = WORKFLOW.read_text(encoding="utf-8").splitlines()

    def test_python_only_changes_trigger_both_unrestricted_governance_events(self):
        self.assertEqual(set(self.events), {"push", "pull_request", "workflow_dispatch"})
        self.assertEqual(self.events["workflow_dispatch"], ("", []))
        for event in ("push", "pull_request"):
            with self.subTest(event=event):
                self.assertEqual(set(children(self.events, event, 4)), {"paths"})
                self.assertLessEqual(P05_PATHS, path_filters(self.events, event))
        self.assertEqual(path_filters(self.events, "push"),
                         path_filters(self.events, "pull_request"))

    def test_all_current_python_sources_and_p05_tests_are_covered(self):
        package_files = {path.relative_to(ROOT).as_posix()
                         for path in (ROOT / "python").rglob("*")
                         if path.is_file() and "__pycache__" not in path.parts}
        test_files = {path.relative_to(ROOT).as_posix()
                      for path in (ROOT / "ci/project").glob("test_p05_*.py")}
        self.assertTrue(package_files)
        self.assertIn(Path(__file__).relative_to(ROOT).as_posix(), test_files)
        required = package_files | test_files | (P05_PATHS - {"python/**"})
        required.add(WORKFLOW.relative_to(ROOT).as_posix())
        for event in ("push", "pull_request"):
            patterns = positive_path_patterns(self.lines, event)
            missing = sorted(path for path in required
                             if not any(pattern.fullmatch(path) for pattern in patterns))
            with self.subTest(event=event):
                self.assertEqual(missing, [], f"{event} omits P05 source inputs")

    def test_full_source_discovery_and_prior_validators_remain_unconditional(self):
        self.assertEqual(set(self.jobs), {"governance"})
        self.assertEqual(set(self.job), {"runs-on", "timeout-minutes", "env", "steps"})
        expected = [
            ("Verify system Python 3.12",
             "python3 -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version; print(sys.version)'"),
            ("Inspect governance prerequisites", "python3 ci/project/preflight.py --tier governance"),
            ("Validate project structure and evidence", "python3 ci/project/check_project.py"),
            ("Check published baseline packet consistency", "python3 ci/project/check_baseline_packets.py"),
        ]
        self.assertEqual([step["name"][0] for step in self.steps[1:]], [
            "Prepare governance evidence directory", *(name for name, _ in expected),
            "Install pinned governance CMake", "Prepare checked governance invocation environment",
            "Test governance tooling", "Retain complete governance packet",
        ])
        for step, (name, command) in zip(self.steps[2:6], expected):
            with self.subTest(step=name):
                self.assertEqual(set(step), {"name", "run"})
                self.assertEqual(step["name"], (name, []))
                self.assertEqual(script(step), command)
        self.assertEqual(set(self.steps[1]), {"name", "run"})
        self.assertEqual(set(self.steps[6]), {"name", "run", "timeout-minutes"})
        self.assertEqual(set(self.steps[7]), {"name", "run"})
        assert_strict_governance_step(self, self.steps[8])
        upload = self.steps[9]
        self.assertEqual(set(upload), {"name", "if", "uses", "with"})
        self.assertEqual(upload["if"], ("always()", []))
        self.assertEqual(upload["uses"], ("actions/upload-artifact@v4", []))

    def test_hosted_system_python_runtime_keeps_existing_privilege_and_budget(self):
        self.assertEqual(set(self.workflow), {
            "name", "on", "permissions", "concurrency", "jobs",
        })
        self.assertEqual(scalars(children(self.workflow, "permissions", 2)), {"contents": "read"})
        self.assertEqual(scalars(children(self.workflow, "concurrency", 2)), {
            "group": "project-governance-${{ github.event_name }}-${{ github.ref }}",
            "cancel-in-progress": "true",
        })
        self.assertEqual(self.job["runs-on"], ("ubuntu-24.04", []))
        self.assertEqual(self.job["timeout-minutes"], ("90", []))
        self.assertEqual(scalars(children(self.job, "env", 6)), {
            "PYTHONDONTWRITEBYTECODE": "'1'",
        })
        checkout = self.steps[0]
        self.assertEqual(set(checkout), {"uses", "with"})
        self.assertEqual(checkout["uses"], ("actions/checkout@v4", []))
        self.assertEqual(scalars(children(checkout, "with", 10)), {
            "fetch-depth": "1", "submodules": "false", "lfs": "false",
            "persist-credentials": "false",
        })


if __name__ == "__main__":
    unittest.main()
