# SPDX-License-Identifier: Apache-2.0
"""Inventory checks use synthetic observations or local Git; no vendor tools run."""

from contextlib import ExitStack
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import hwemu_inventory as inventory
import test_baseline_inventory as fixtures


CLEAN_SOURCE = {
    "revision": "a" * 40,
    "tree": "b" * 40,
    "dirty": False,
    "outcome": "pass",
    "blockers": [],
    "submodules": {"declared_count": 0, "entries": [], "errors": []},
}


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.source = self.stack.enter_context(mock.patch.object(
            inventory.hwemu_source, "collect_source",
            return_value=copy.deepcopy(CLEAN_SOURCE)))
        self.which = self.stack.enter_context(mock.patch.object(
            inventory.shutil, "which", return_value="/private/vendor/executable"))
        self.disk = self.stack.enter_context(mock.patch.object(
            inventory.shutil, "disk_usage", return_value=SimpleNamespace(free=40 * inventory.GIB)))
        self.memory = self.stack.enter_context(mock.patch.object(
            inventory.preflight, "available_memory_bytes", return_value=8 * inventory.GIB))
        self.stack.enter_context(mock.patch.object(
            subprocess, "Popen", side_effect=AssertionError("unexpected executable invocation")))
        self.stack.enter_context(mock.patch.object(
            subprocess, "run", side_effect=AssertionError("unexpected executable invocation")))

    def test_all_tools_present_still_needs_qualification_and_artifacts(self):
        report = inventory.inventory("/private/source")
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["target"], "hw_emu")
        self.assertEqual(report["outcome"], "blocked")
        self.assertFalse(report["execution_performed"])
        self.assertFalse(report["phase_complete"])
        self.assertFalse(report["vendor_qualification_verified"])
        self.assertEqual(len(report["blockers"]), 3)
        self.assertTrue(all(item["available"] for item in report["vendor_tools"].values()))
        self.assertTrue(any("platform" in text for text in report["blockers"]))
        self.assertTrue(any("artifacts" in text for text in report["blockers"]))
        self.assertTrue(any("license" in text for text in report["blockers"]))

    def test_missing_tools_are_named_without_paths(self):
        self.which.return_value = None
        report = inventory.inventory("/private/source")
        self.assertEqual(sum("vendor PATH tool missing:" in value for value in report["blockers"]), 5)
        self.assertFalse(any(item["available"] for item in report["vendor_tools"].values()))
        self.assertNotIn("/private", json.dumps(report))

    def test_xrt_smi_is_a_presence_alternative_not_a_command(self):
        self.which.side_effect = lambda name: "/private/xrt-smi" if name == "xrt-smi" else None
        report = inventory.inventory("/private/source")
        self.assertTrue(report["vendor_tools"]["xrt_inventory"]["available"])
        self.assertFalse(report["execution_performed"])

    def test_environment_values_and_license_addresses_are_never_reported(self):
        environment = {name: "/private/secret-root" for name in inventory.VENDOR_ROOT_VARIABLES}
        environment.update(XILINXD_LICENSE_FILE="private-server:1234",
                           LM_LICENSE_FILE="private-server:5678", PATH="/private/bin")
        with mock.patch.dict(os.environ, environment, clear=True):
            report = inventory.inventory("/private/source")
        self.assertTrue(all(report["vendor_roots_present"].values()))
        serialized = json.dumps(report)
        for secret in ("/private", "private-server", "XILINXD_LICENSE_FILE", "LM_LICENSE_FILE"):
            self.assertNotIn(secret, serialized)

    def test_empty_root_variables_are_not_present(self):
        with mock.patch.dict(os.environ, {name: "" for name in inventory.VENDOR_ROOT_VARIABLES}, clear=True):
            report = inventory.inventory("/private/source")
        self.assertFalse(any(report["vendor_roots_present"].values()))

    def test_low_resources_block_without_claiming_a_container_limit(self):
        self.disk.return_value = SimpleNamespace(free=14 * inventory.GIB)
        self.memory.return_value = 5 * inventory.GIB
        report = inventory.inventory("/private/source")
        self.assertTrue(any("disk" in text for text in report["blockers"]))
        self.assertTrue(any("memory" in text for text in report["blockers"]))
        self.assertIsNone(report["resources"]["cgroup_limit_bytes"])
        self.assertEqual(report["default_budget"]["jobs"], 2)
        self.assertEqual(report["default_budget"]["min_free_bytes"], 15 * inventory.GIB)
        self.assertEqual(report["default_budget"]["max_rss_bytes"], 6 * inventory.GIB)

    def test_unknown_resources_are_blocked_and_exception_paths_are_redacted(self):
        self.disk.side_effect = OSError("private source path")
        self.memory.return_value = None
        report = inventory.inventory("/private/source")
        self.assertIsNone(report["resources"]["free_disk_bytes"])
        self.assertIsNone(report["resources"]["available_memory_bytes"])
        self.assertNotIn("private source path", json.dumps(report))

    def test_report_cannot_mutate_default_budget(self):
        report = inventory.inventory("/private/source")
        report["default_budget"]["jobs"] = 999
        self.assertEqual(inventory.inventory("/private/source")["default_budget"]["jobs"], 2)

    def test_source_dirty_and_submodule_details_are_reduced_to_fixed_messages(self):
        value = copy.deepcopy(CLEAN_SOURCE)
        value.update(dirty=True, outcome="blocked", blockers=["secret error /private/path"],
                     changed_paths=["secret-file"], untracked_paths=["secret-input"])
        value["submodules"] = {"declared_count": 1, "entries": [{
            "path": "secret-submodule", "revision": "c" * 40, "status": "not_initialized"}],
            "errors": ["secret-submodule failed"]}
        self.source.return_value = value
        report = inventory.observe_source("/private/source")
        self.assertEqual(report["outcome"], "blocked")
        self.assertTrue(report["dirty"])
        self.assertFalse(report["clean"])
        self.assertEqual(report["submodules"]["initialized_count"], 0)
        self.assertFalse(report["submodules"]["at_recorded_revisions"])
        self.assertNotIn("secret", json.dumps(report))
        self.assertNotIn("/private", json.dumps(report))

    def test_source_failure_keeps_unknown_identity_and_no_raw_exception(self):
        self.source.side_effect = ValueError("secret error")
        report = inventory.observe_source("/private/source")
        self.assertEqual(report["outcome"], "blocked")
        self.assertIsNone(report["revision"])
        self.assertIsNone(report["tree"])
        self.assertIsNone(report["dirty"])
        self.assertNotIn("secret", json.dumps(report))

    def test_malformed_source_identity_cannot_be_a_pass(self):
        value = copy.deepcopy(CLEAN_SOURCE)
        value.update(revision="secret-version", tree="B" * 40, dirty=0)
        self.source.return_value = value
        report = inventory.observe_source("/private/source")
        self.assertEqual(report["outcome"], "blocked")
        self.assertIsNone(report["revision"])
        self.assertIsNone(report["tree"])
        self.assertIsNone(report["dirty"])


class LocalGitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "source"
        fixtures.populate_source(self.root)
        for name in inventory.hwemu_source.REQUIRED_SOURCE_INPUTS:
            if not (self.root / name).exists():
                fixtures.write(self.root / name, "inert source fixture\n")
        fixtures.git(self.root, "init", "-q")
        fixtures.git(self.root, "add", ".")
        fixtures.git(self.root, "commit", "-qm", "inert source fixture")

    def test_actual_git_identity_is_observed_without_source_changes(self):
        before = {name: (self.root / name).read_bytes() for name in fixtures.SOURCE_FILES}
        report = inventory.observe_source(self.root)
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(report["revision"], fixtures.git(self.root, "rev-parse", "HEAD"))
        self.assertEqual(report["tree"], fixtures.git(self.root, "rev-parse", "HEAD^{tree}"))
        self.assertFalse(report["dirty"])
        self.assertTrue(report["clean"])
        self.assertEqual(before, {name: (self.root / name).read_bytes() for name in fixtures.SOURCE_FILES})
        self.assertNotIn(str(self.base), json.dumps(report))

    def test_actual_untracked_input_is_reported_without_its_name(self):
        (self.root / "secret-input.txt").write_text("private source input")
        report = inventory.observe_source(self.root)
        self.assertEqual(report["outcome"], "blocked")
        self.assertTrue(report["dirty"])
        self.assertNotIn("secret-input", json.dumps(report))

    def test_discovered_executable_files_are_not_executed(self):
        binaries = self.base / "vendor-bin"
        binaries.mkdir()
        marker = self.base / "vendor-executed"
        for candidates in inventory.VENDOR_TOOLS.values():
            for name in candidates:
                path = binaries / name
                path.write_text("#!/bin/sh\nprintf invoked > '" + str(marker) + "'\n")
                path.chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": str(binaries) + os.pathsep + os.environ["PATH"]}):
            report = inventory.inventory(self.root)
        self.assertTrue(all(item["available"] for item in report["vendor_tools"].values()))
        self.assertFalse(marker.exists())
        self.assertEqual(report["outcome"], "blocked")
        self.assertFalse(report["execution_performed"])


if __name__ == "__main__":
    unittest.main()
