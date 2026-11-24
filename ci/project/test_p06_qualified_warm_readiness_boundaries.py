# SPDX-License-Identifier: Apache-2.0
"""Readiness prerequisite boundaries using tiny files and synthetic source snapshots."""

from contextlib import ExitStack
from copy import deepcopy
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest import mock

import p06_qualified_warm_readiness as readiness


REVISION = "a" * 40
DEPENDENCIES = ("softfloat", "ramulator")


def indexed(checks):
    return {row["id"]: row for row in checks.rows}


class HostPrerequisiteBoundaryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="p06-readiness-host-boundary-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.host = self.root / "host-bin"
        self.python = self.root / "python-bin/python3"
        self.host.mkdir()
        self.python.parent.mkdir()
        self.roots = {"host_bin": self.host, "workspace_dir": self.root / "workspace"}
        for name in (*readiness.preparation.HOST_TOOLS, *readiness.NATIVE_HOST_ALIASES):
            path = self.python if name == "python3" else self.host / name
            path.write_bytes(("synthetic executable " + name + "\n").encode())
            path.chmod(0o755)
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        self.context.enter_context(mock.patch.object(readiness.sys, "executable", str(self.python)))
        self.context.enter_context(mock.patch.object(readiness.sys, "version_info", (3, 12, 14, "final", 0)))
        self.context.enter_context(mock.patch.object(readiness.sys, "platform", "linux"))
        self.context.enter_context(mock.patch.object(readiness.platform, "python_implementation", return_value="CPython"))

    @staticmethod
    def synthetic_version(argv, **kwargs):
        return 0, b"Python 3.12.14\n" if Path(argv[0]).name == "python3" else b"cmake version 3.22.6\n"

    def observe(self, *, preparation_available=False):
        checks = readiness._Checks()
        helper = ({"wraps": readiness.preparation._host_tools} if preparation_available else
                  {"side_effect": AssertionError("dependent host reader must remain uncalled")})
        with mock.patch.object(readiness.preparation, "_host_tools", **helper) as selection, \
                mock.patch.object(readiness.inventory, "_probe", side_effect=self.synthetic_version) as probe:
            readiness._inspect_host(self.roots, checks)
        return indexed(checks), selection, probe

    def assert_independent_observations(self, rows, probe, *, missing=(), executing=True):
        for name in (*readiness.preparation.HOST_TOOLS, *readiness.NATIVE_HOST_ALIASES):
            self.assertEqual(rows["host.alias:" + name]["status"],
                             "blocked" if name in missing else "observed", name)
        self.assertEqual(rows["host.executing_python"]["status"], "observed" if executing else "blocked")
        self.assertEqual(rows["host.interpreter_binding"]["status"],
                         "observed" if executing and "python3" not in missing else "not_checked")
        for name in ("python3", "cmake"):
            self.assertEqual(rows["host.version:" + name]["status"],
                             "not_checked" if name in missing else "observed", name)
        self.assertEqual([Path(call.args[0][0]).name for call in probe.call_args_list],
                         [name for name in ("python3", "cmake") if name not in missing])
        self.assertFalse(self.roots["workspace_dir"].exists())

    def assert_selection_skipped(self, rows, selection):
        selection.assert_not_called()
        row = rows["host.preparation_selection"]
        self.assertEqual(row["status"], "not_checked")
        self.assertIsNone(row["observed"])
        self.assertIn("bounded host executable identities are incomplete", row["reason"])

    def test_executable_fifo_selected_by_which_never_reaches_dependent_host_reader(self):
        fifo = self.host / "gcc"
        fifo.unlink()
        os.mkfifo(fifo, 0o755)
        fifo.chmod(0o755)
        self.assertEqual(shutil.which("gcc", path=str(self.host)), str(fifo))
        rows, selection, probe = self.observe()
        self.assert_selection_skipped(rows, selection)
        self.assertIn("nonregular or oversized", rows["host.alias:gcc"]["reason"])
        self.assert_independent_observations(rows, probe, missing=("gcc",))
        self.assertTrue(stat.S_ISFIFO(fifo.stat().st_mode))

    def test_oversized_selected_tool_is_rejected_before_dependent_rehash(self):
        oversized = self.host / "gcc"
        oversized.write_bytes(b"x" * 65)
        self.assertEqual(shutil.which("gcc", path=str(self.host)), str(oversized))
        with mock.patch.object(readiness.dependency, "MAX_FILE_BYTES", 64):
            rows, selection, probe = self.observe()
        self.assert_selection_skipped(rows, selection)
        self.assertIn("nonregular or oversized", rows["host.alias:gcc"]["reason"])
        self.assert_independent_observations(rows, probe, missing=("gcc",))
        self.assertEqual(oversized.read_bytes(), b"x" * 65)

    def test_each_missing_preparation_alias_skips_only_its_dependent_observations(self):
        real_which = shutil.which
        for missing in readiness.preparation.HOST_TOOLS:
            with self.subTest(missing=missing):
                def unavailable(name, **kwargs):
                    return None if name == missing else real_which(name, **kwargs)
                with mock.patch.object(readiness.shutil, "which", side_effect=unavailable):
                    rows, selection, probe = self.observe()
                self.assert_selection_skipped(rows, selection)
                self.assertIn("required host alias is absent", rows["host.alias:" + missing]["reason"])
                self.assert_independent_observations(rows, probe, missing=(missing,))

    def test_unavailable_executing_python_skips_rehash_while_valid_selected_versions_continue(self):
        selected = self.host / "python3"
        selected.write_bytes(b"synthetic selected Python\n")
        selected.chmod(0o755)
        executing = self.root / "executing-python"
        os.mkfifo(executing, 0o755)
        executing.chmod(0o755)
        with mock.patch.object(readiness.sys, "executable", str(executing)):
            rows, selection, probe = self.observe()
        self.assert_selection_skipped(rows, selection)
        self.assertIn("nonregular or oversized", rows["host.executing_python"]["reason"])
        self.assertEqual(rows["host.alias:python3"]["observed"]["path"], str(selected))
        self.assert_independent_observations(rows, probe, executing=False)
        self.assertTrue(stat.S_ISFIFO(executing.stat().st_mode))

    def test_missing_native_only_aliases_do_not_suppress_preparation_selection(self):
        real_which = shutil.which
        for missing in readiness.NATIVE_HOST_ALIASES:
            with self.subTest(missing=missing):
                def unavailable(name, **kwargs):
                    return None if name == missing else real_which(name, **kwargs)
                with mock.patch.object(readiness.shutil, "which", side_effect=unavailable):
                    rows, selection, probe = self.observe(preparation_available=True)
                selection.assert_called_once_with(self.host)
                self.assertEqual(rows["host.preparation_selection"]["status"], "observed")
                self.assert_independent_observations(rows, probe, missing=(missing,))


class CanonicalRootBoundaryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="p06-readiness-root-boundary-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        (self.root / "target").mkdir()
        (self.root / "existing").mkdir()

    def assert_parent_segments_rejected(self, *, planned, target):
        literals = (str(self.root / "existing" / ".." / target),
                    str(self.root / "absent" / ".." / target),
                    str(self.root / "target" / ".."))
        for literal in literals:
            with self.subTest(literal=literal), \
                    mock.patch.object(readiness.base, "_path", side_effect=AssertionError(
                        "parent components must be rejected before path normalization")) as normalize:
                with self.assertRaisesRegex(ValueError, "canonical absolute path"):
                    readiness._root(literal, planned=planned)
                normalize.assert_not_called()
        self.assertFalse((self.root / "absent").exists())

    def test_existing_roots_reject_parent_components_before_normalization(self):
        self.assert_parent_segments_rejected(planned=False, target="target")

    def test_planned_roots_reject_parent_components_before_normalization(self):
        self.assert_parent_segments_rejected(planned=True, target="planned")
        self.assertFalse((self.root / "planned").exists())

    def test_canonical_existing_and_planned_roots_remain_available_without_creation(self):
        existing, planned = self.root / "target", self.root / "planned"
        self.assertEqual(readiness._root(str(existing)), existing)
        self.assertEqual(readiness._root(str(existing), planned=True), existing)
        self.assertEqual(readiness._root(str(planned), planned=True), planned)
        self.assertFalse(planned.exists())


class SourceClosureBoundaryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="p06-readiness-source-boundary-")
        self.addCleanup(directory.cleanup)
        self.source = Path(directory.name).resolve()

    @staticmethod
    def synthetic_snapshot():
        entries = [{"path": readiness.dependency.PINS[name]["path"],
                    "revision": readiness.dependency.PINS[name]["revision"],
                    "status": "initialized"} for name in reversed(DEPENDENCIES)]
        return {"revision": REVISION, "tree": "b" * 40, "dirty": False,
                "changed_paths": [], "untracked_paths": [], "pins": {},
                "submodules": {"entries": entries, "declared_count": 2, "errors": []},
                "blockers": [], "inputs": [], "outcome": "pass"}

    @staticmethod
    def incomplete(snapshot):
        snapshot["dirty"] = None
        snapshot["outcome"] = "blocked"
        snapshot["submodules"]["errors"].append("source or recursive submodule observation is incomplete")
        snapshot["blockers"].append("source identity could not be completely verified")
        return snapshot

    def observe(self, snapshot, *, local=None):
        original = deepcopy(snapshot)
        checks = readiness._Checks()
        with mock.patch.object(readiness.hwemu_source, "collect_source", return_value=snapshot) as collect, \
                mock.patch.object(readiness, "_local_inputs", side_effect=local,
                                  return_value={"untracked": 0, "ignored": 0}) as local_inputs:
            readiness._inspect_source({"expected_revision": REVISION}, {"source_dir": self.source}, checks)
        collect.assert_called_once_with(self.source)
        self.assertEqual(local_inputs.call_args_list, [
            mock.call(self.source / readiness.dependency.PINS[name]["path"]) for name in DEPENDENCIES])
        self.assertEqual(snapshot, original)
        return indexed(checks)

    def assert_unavailable_closure(self, rows):
        self.assertEqual(rows["source.raw_recursive"]["status"], "blocked")
        self.assertEqual(rows["source.revision"]["status"], "observed")
        self.assertEqual(rows["source.revision"]["observed"], REVISION)
        for name in DEPENDENCIES:
            row = rows["source.dependency_gitlink:" + name]
            self.assertEqual(row["status"], "not_checked", name)
            self.assertIsNone(row["observed"])
            self.assertIn("complete raw recursive source observation is unavailable", row["reason"])

    def test_provisional_initialized_entry_from_incomplete_child_is_not_observed(self):
        snapshot = self.incomplete(self.synthetic_snapshot())
        snapshot["submodules"]["entries"] = snapshot["submodules"]["entries"][:1]
        rows = self.observe(snapshot, local=[{"untracked": 0, "ignored": 0},
                            ValueError("synthetic unavailable child Git metadata")])
        self.assert_unavailable_closure(rows)
        self.assertIsNone(rows["source.raw_recursive"]["observed"]["dirty"])
        self.assertEqual(rows["source.raw_recursive"]["observed"]["submodules"], snapshot["submodules"])
        self.assertEqual(rows["source.local_inputs:softfloat"]["status"], "observed")
        self.assertEqual(rows["source.local_inputs:ramulator"]["status"], "blocked")

    def test_missing_child_closure_does_not_promote_another_initialized_dependency(self):
        snapshot = self.synthetic_snapshot()
        snapshot["submodules"]["entries"][-1]["status"] = "not_initialized"
        snapshot["submodules"]["errors"] = ["a recorded submodule is not initialized"]
        snapshot["blockers"] = list(snapshot["submodules"]["errors"])
        snapshot["outcome"] = "blocked"
        rows = self.observe(snapshot, local=[ValueError("synthetic absent dependency worktree"),
                            {"untracked": 0, "ignored": 0}])
        self.assert_unavailable_closure(rows)
        self.assertIs(rows["source.raw_recursive"]["observed"]["dirty"], False)
        self.assertEqual(rows["source.local_inputs:softfloat"]["status"], "blocked")
        self.assertEqual(rows["source.local_inputs:ramulator"]["status"], "observed")

    def test_nested_revision_mismatch_cannot_promote_initialized_parent(self):
        snapshot = self.incomplete(self.synthetic_snapshot())
        parent = snapshot["submodules"]["entries"][0]
        snapshot["submodules"]["entries"] = [parent, {
            "path": parent["path"] + "/synthetic-child", "revision": "c" * 40,
            "status": "revision_mismatch"}]
        rows = self.observe(snapshot)
        self.assert_unavailable_closure(rows)
        for name in DEPENDENCIES:
            self.assertEqual(rows["source.local_inputs:" + name]["status"], "observed")

    def test_bounded_out_partial_and_full_entry_lists_do_not_establish_closure(self):
        for stage in ("recursive_prepare", "worktree_observation"):
            with self.subTest(synthetic_limit_stage=stage):
                snapshot = self.incomplete(self.synthetic_snapshot())
                if stage == "recursive_prepare":
                    snapshot["submodules"]["entries"] = snapshot["submodules"]["entries"][:1]
                else:
                    snapshot["changed_paths"] = ["synthetic-tracked-input"]
                rows = self.observe(snapshot)
                self.assert_unavailable_closure(rows)
                self.assertIsNone(rows["source.raw_recursive"]["observed"]["dirty"])
                for name in DEPENDENCIES:
                    self.assertEqual(rows["source.local_inputs:" + name]["status"], "observed")

    def test_completed_dirty_observation_keeps_revision_and_local_inputs_independent(self):
        snapshot = self.synthetic_snapshot()
        snapshot.update(dirty=True, changed_paths=["synthetic-tracked-input"], outcome="blocked",
                        blockers=["source contains tracked changes or nonignored untracked inputs"])
        rows = self.observe(snapshot, local=[{"untracked": 1, "ignored": 0},
                            {"untracked": 0, "ignored": 0}])
        self.assert_unavailable_closure(rows)
        self.assertIs(rows["source.raw_recursive"]["observed"]["dirty"], True)
        self.assertEqual(rows["source.local_inputs:softfloat"]["status"], "blocked")
        self.assertEqual(rows["source.local_inputs:ramulator"]["status"], "observed")

    def test_complete_clean_closure_observes_each_matching_initialized_pin(self):
        snapshot = self.synthetic_snapshot()
        rows = self.observe(snapshot)
        self.assertTrue(all(row["status"] == "observed" for row in rows.values()), rows)
        for name in DEPENDENCIES:
            row = rows["source.dependency_gitlink:" + name]
            self.assertEqual(row["expected"], {"revision": readiness.dependency.PINS[name]["revision"],
                                              "status": "initialized"})
            self.assertEqual(row["observed"], next(entry for entry in snapshot["submodules"]["entries"]
                             if entry["path"] == readiness.dependency.PINS[name]["path"]))

    def test_complete_raw_closure_does_not_replace_revision_and_dependency_pin_checks(self):
        snapshot = self.synthetic_snapshot()
        snapshot["revision"] = "d" * 40
        snapshot["submodules"]["entries"][0]["revision"] = "e" * 40
        rows = self.observe(snapshot)
        self.assertEqual(rows["source.raw_recursive"]["status"], "observed")
        self.assertEqual(rows["source.revision"]["status"], "blocked")
        self.assertEqual(rows["source.dependency_gitlink:ramulator"]["status"], "blocked")
        self.assertEqual(rows["source.dependency_gitlink:softfloat"]["status"], "observed")
        for name in DEPENDENCIES:
            self.assertEqual(rows["source.local_inputs:" + name]["status"], "observed")


if __name__ == "__main__":
    unittest.main()
