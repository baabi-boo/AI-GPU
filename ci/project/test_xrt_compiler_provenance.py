# SPDX-License-Identifier: Apache-2.0
"""Compiler helper snapshots and drift guards using inert runner fixtures."""

import ast
import hashlib
from pathlib import Path
import unittest
from unittest import mock

import xrt_baseline
from test_xrt_baseline import RunnerFixture, STAGES


SOURCE_HELPERS = Path(__file__).resolve().parent


def compiler_helper_closure():
    pending = ["compiler_records.py"]
    visited = set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        tree = ast.parse((SOURCE_HELPERS / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                modules = [node.module] if node.module else []
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue
            for module in modules:
                dependency = module.split(".")[0] + ".py"
                if (SOURCE_HELPERS / dependency).is_file():
                    pending.append(dependency)
    return visited


def raw_identity(contents):
    return {"sha256": hashlib.sha256(contents).hexdigest(), "size_bytes": len(contents)}


class CompilerHelperProvenanceTests(RunnerFixture):
    def test_inventory_hashes_complete_local_import_closure(self):
        closure = compiler_helper_closure()
        self.assertIn("baseline_packet_contract.py", closure)
        self.assertIn("baseline_matrix.py", closure)
        self.assertIn("baseline_packet_io.py", closure)
        inventory = xrt_baseline.tooling_inventory()
        self.assertTrue(closure <= inventory.keys(), closure - inventory.keys())
        for name in closure:
            with self.subTest(helper=name):
                contents = (self.helpers / name).read_bytes()
                self.assertEqual(contents, (SOURCE_HELPERS / name).read_bytes())
                self.assertEqual(inventory[name], raw_identity(contents))

    def test_completed_fixture_retains_original_bytes_for_import_closure(self):
        originals = {name: (self.helpers / name).read_bytes()
                     for name in compiler_helper_closure()}
        report = self.run_fixture()
        self.assertEqual(report["outcome"], "pass", report.get("reason"))
        stored = self.assertFinished(report)
        self.assertEqual([call["id"] for call in self.calls], list(STAGES))
        retained = {record["path"]: record for record in report["retained"]}
        stored_retained = {record["path"]: record for record in stored["retained"]}
        for name, contents in originals.items():
            with self.subTest(helper=name):
                selected = self.fixture.output / "artifacts/tooling" / name
                expected = raw_identity(contents)
                self.assertEqual(selected.read_bytes(), contents)
                self.assertEqual(report["tooling_before"][name], expected)
                self.assertEqual(retained[str(selected)], {"path": str(selected), **expected})
                public_path = "$OUTPUT/artifacts/tooling/" + name
                self.assertEqual(stored_retained[public_path], {"path": public_path, **expected})

    def assert_live_drift_stops_before_execution(self, name):
        args, paths, report = self.plan()
        self.assertEqual(report["outcome"], "pass", report.get("blockers"))
        original = (self.helpers / name).read_bytes()
        (self.helpers / name).write_bytes(original + b"\n# Altered isolated helper.\n")
        result = xrt_baseline.execute_run(args, report, paths)
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("executing helpers changed after planning", result["reason"])
        self.assertEqual(result["tooling_before"][name], raw_identity(original))
        self.runner.assert_not_called()
        self.host_observation.assert_not_called()
        self.runtime_observation.assert_not_called()
        self.assertEqual(result["commands"], [])
        self.assertEqual(result["integration"]["outcome"], "not_run")
        self.assertIsNone(result["integration"]["exit_code"])
        self.assertFinished(result)

    def test_compiler_validator_drift_stops_before_execution(self):
        self.assert_live_drift_stops_before_execution("compiler_records.py")

    def test_transitive_matrix_helper_drift_stops_before_execution(self):
        self.assert_live_drift_stops_before_execution("baseline_matrix.py")

    def assert_retained_drift_prevents_success(self, name):
        original = (self.helpers / name).read_bytes()
        retained_helper = self.fixture.output / "artifacts/tooling" / name
        last_configuration = self.fixture.output / "artifacts/hw_VX_types.vh"
        original_retain = xrt_baseline._retain
        mutations = []

        def retain_then_mutate(path, destination, *args, **kwargs):
            retained = original_retain(path, destination, *args, **kwargs)
            if destination == last_configuration:
                retained_helper.write_bytes(original + b"\n# Altered retained helper.\n")
                mutations.append(retained_helper)
            return retained

        with mock.patch.object(xrt_baseline, "_retain", side_effect=retain_then_mutate):
            report = self.run_fixture()

        self.assertEqual(mutations, [retained_helper])
        self.assertEqual((self.helpers / name).read_bytes(), original)
        self.assertEqual([call["id"] for call in self.calls], list(STAGES))
        self.assertEqual(report["outcome"], "fail")
        self.assertIn("retained artifact changed before final recording", report["reason"])
        self.assertEqual(report["integration"]["outcome"], "fail")
        self.assertEqual(report["integration"]["exit_code"], 0)
        self.assertIs(report["reference_markers_verified"], True)
        self.assertIn({"path": str(retained_helper), **raw_identity(original)}, report["retained"])
        self.assertFinished(report)

    def test_changed_retained_validator_cannot_enter_successful_packet(self):
        self.assert_retained_drift_prevents_success("compiler_records.py")

    def test_changed_retained_transitive_io_cannot_enter_successful_packet(self):
        self.assert_retained_drift_prevents_success("baseline_packet_io.py")

    def test_transient_source_change_during_helper_copy_stops_before_execution(self):
        helper = self.helpers / "baseline_packet_contract.py"
        original = helper.read_bytes()
        destination = self.fixture.output / "artifacts/tooling/baseline_packet_contract.py"
        original_retain = xrt_baseline._retain
        mutations = []

        def mutate_then_retain(path, selected, *args, **kwargs):
            if selected != destination:
                return original_retain(path, selected, *args, **kwargs)
            helper.write_bytes(original + b"\n# Transient isolated-helper change.\n")
            mutations.append(helper)
            try:
                return original_retain(path, selected, *args, **kwargs)
            finally:
                helper.write_bytes(original)

        with mock.patch.object(xrt_baseline, "_retain", side_effect=mutate_then_retain):
            report = self.run_fixture()

        self.assertEqual(mutations, [helper])
        self.assertEqual(helper.read_bytes(), original)
        self.assertEqual(report["outcome"], "fail")
        self.assertIn("retained input differs from its frozen identity", report["reason"])
        self.runner.assert_not_called()
        self.assertEqual(report["commands"], [])
        self.assertEqual(report["integration"]["outcome"], "not_run")
        self.assertFalse(destination.exists())
        self.assertFinished(report)


if __name__ == "__main__":
    unittest.main()
