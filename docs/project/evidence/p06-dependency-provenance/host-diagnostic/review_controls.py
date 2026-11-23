#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exercise diagnostic map and failed-intake boundaries without compilation."""

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


DRIVER_PATH = Path(__file__).with_name("driver.py").resolve()
HELPERS = None
PREPARED = None
BINARY = None
spec = importlib.util.spec_from_file_location("diagnostic_under_review", DRIVER_PATH)
DRIVER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(DRIVER)


def identity(path):
    body = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}


class ProjectLoadTests(unittest.TestCase):
    source = Path("/trusted-checkout")
    workspace = Path("/diagnostic/workspace")
    cwd = workspace / "dependency-build/extension"
    expected = [
        {"path": str(cwd / "gddr6.o")},
        {"path": str(workspace / "dependency-sources/ramulator/libramulator.so")},
    ]

    def check(self, loads, *, external=()):
        text = BINARY.MAP_HEADING + "\n\n" + "\n".join("LOAD " + name for name in loads) + "\n"
        parsed = BINARY.validate_link_map(text, cwd=str(self.cwd), archives={},
            required_archives=[], required_loads=[self.expected[1]["path"]])
        DRIVER.validate_project_loads(parsed, self.expected, source=self.source,
            workspace=self.workspace, external_archives=external)

    def test_exact_inputs_and_unqualified_system_population_pass(self):
        self.check([row["path"] for row in self.expected] + ["/usr/lib/libstdc++.so"])
        self.check(["./gddr6.o", "../../dependency-sources/ramulator/libramulator.so"])

    def test_extra_source_build_output_and_temporary_loads_reject(self):
        for extra in ("/trusted-checkout/./unplanned.so",
                      "../tmp/unplanned.o", "../../evidence/unplanned.so",
                      "../../dependency-sources/ramulator/unplanned.so"):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "unplanned source/workspace input"):
                self.check([row["path"] for row in self.expected] + [extra])

    def test_relative_duplicate_object_rejects(self):
        with self.assertRaisesRegex(ValueError, "omits or repeats an actual direct input"):
            self.check([row["path"] for row in self.expected] + ["./gddr6.o"])

    def test_missing_direct_object_rejects(self):
        with self.assertRaisesRegex(ValueError, "omits or repeats an actual direct input"):
            self.check([self.expected[1]["path"]])

    def test_only_preverified_compiler_support_paths_are_exempt(self):
        external = str(self.workspace / "tools/libgcc.a")
        loads = [row["path"] for row in self.expected] + [external, external]
        self.check(loads, external=[external])
        with self.assertRaisesRegex(ValueError, "unplanned source/workspace input"):
            self.check(loads)


class FailedIntakeTests(unittest.TestCase):
    def exercise(self, *, missing):
        with tempfile.TemporaryDirectory(prefix="p06-diagnostic-intake-review-") as temporary:
            workspace = Path(temporary).resolve()
            output = workspace / "evidence"
            output.mkdir()
            observed = json.loads(PREPARED.read_text())
            observed["driver"] = identity(DRIVER_PATH)
            prepared = workspace / "prepared.json"
            prepared.write_text(json.dumps(observed) + "\n")
            original = json.loads((PREPARED.parent / "evidence/host-diagnostic.json").read_text())
            result = copy.deepcopy(original)
            result["observations"] = observed
            result["prepared"] = identity(prepared)
            report = output / "host-diagnostic.json"
            report.write_text(json.dumps(result) + "\n")
            if not missing:
                (output / "tool-config.json").write_text("{}\n")
            argv = [sys.executable, "-I", "-B", str(DRIVER_PATH), "run", "--helpers", str(HELPERS),
                    "--workspace", str(workspace)]
            run = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
            self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
            self.assertTrue((workspace / "execution-started").is_file())
            saved = json.loads(report.read_text())
            self.assertEqual((saved["state"], saved["outcome"]), ("finished", "blocked"))
            expected = "No such file or directory" if missing else "recorder configuration changed"
            self.assertIn(expected, saved["reason"])
            self.assertEqual(saved["failures"][0]["reason"], saved["reason"])
            self.assertGreaterEqual(len(saved["failures"]), 2)
            self.assertEqual(saved["observations"]["commands"], [])
            self.assertEqual(saved["observations"]["record_identities"], [])
            self.assertFalse(saved["host_diagnostic_passed"])
            self.assertFalse(saved["fresh_dependency_build_passed"])
            self.assertEqual(saved["native_execution"], "not_run")
            first = report.read_bytes()
            repeated = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, timeout=15)
            self.assertEqual(repeated.returncode, 1)
            self.assertIn("diagnostic already attempted", repeated.stdout)
            self.assertEqual(report.read_bytes(), first)

    def test_changed_configuration_retains_first_failure_and_rejects_retry(self):
        self.exercise(missing=False)

    def test_absent_configuration_retains_first_failure_and_rejects_retry(self):
        self.exercise(missing=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helpers", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    args = parser.parse_args()
    HELPERS, PREPARED = args.helpers.resolve(strict=True), args.prepared.resolve(strict=True)
    sys.path.insert(0, str(HELPERS / "ci/project"))
    import p06_dependency_binary as BINARY
    unittest.main(argv=[sys.argv[0], "-v"])
