# SPDX-License-Identifier: Apache-2.0
"""Compare isolated producer import closures with their inert replay contracts."""

import json
from pathlib import Path
import subprocess
import sys
import unittest

import p06_dependency_control_replay as controls
import p06_dependency_native_replay as native


ROOT = Path(__file__).resolve().parents[2]


class HostedHelperClosureReviewTests(unittest.TestCase):
    def closure(self, modules):
        # Keep replay/test imports out of the actual producer process. The
        # production launchers run the same entry points in separate processes.
        code = "\n".join((
            "import importlib, json, sys",
            "sys.path.insert(0, " + repr(str(ROOT / "ci/project")) + ")",
            *("importlib.import_module(" + repr(module) + ")" for module in modules),
            "import p06_managed_preflight_execute as producer",
            "print(json.dumps([row['path'] for row in producer.loaded_helpers()]))",
        ))
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code],
            cwd=ROOT, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_native_dependency_entrypoint_closure_matches_reader(self):
        # execute(..., lifetime=True, dependency=True) imports these selected
        # contracts/validators before freezing loaded_helpers().
        actual = self.closure(("p06_dependency_lifetime_execute",
            "p06_native_lifetime_contract", "p06_dependency_admission",
            "p06_native_lifetime_records"))
        self.assertEqual(actual, sorted(native.RUNNER_HELPERS))

    def test_pending_probe_closure_matches_reader(self):
        # The dependency contract is imported when the probe admits a managed
        # dependency report; all other imports belong to its public entry point.
        actual = self.closure(("p06_pending_probe", "p06_dependency_contract"))
        self.assertEqual(actual, sorted(controls.PROBE_HELPERS))

    def test_substitution_control_closure_matches_reader(self):
        actual = self.closure(("p06_dependency_substitution",))
        self.assertEqual(actual, sorted(controls.SUBSTITUTION_HELPERS))


if __name__ == "__main__":
    unittest.main()
