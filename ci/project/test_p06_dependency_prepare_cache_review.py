# SPDX-License-Identifier: Apache-2.0
"""Real Git controls for relocating a hosted toolchain before source inventory.

Only resource availability and the six remote-acquisition commands are mocked.
Source cleanliness, both initialized gitlinks, cache paths and byte preservation
use real temporary repositories. These fixtures establish no native execution.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import baseline_inventory as inventory
import p06_dependency_contract as contract
import p06_dependency_prepare as prepare


class HostedCachePreparationReviewTests(unittest.TestCase):
    def git(self, root, *arguments):
        return subprocess.check_output([
            "git", "-c", "core.hooksPath=/dev/null", "-c", "protocol.file.allow=always",
            "-c", "user.name=Preparation Fixture", "-c", "user.email=fixture@example.invalid",
            "-C", str(root), *arguments], stderr=subprocess.DEVNULL)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-hosted-cache-review-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source, self.workspace = self.root / "source", self.root / "workspace"
        self.source.mkdir()
        self.workspace.mkdir()
        self.git(self.source, "init", "-q")
        for name in inventory.SOURCE_INPUTS:
            if name == ".gitmodules":
                continue
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((prepare.ROOT / "VERSION").read_bytes() if name == "VERSION"
                             else ("fixture input: " + name + "\n").encode())
        pins = deepcopy(contract.PINS)
        for name in ("softfloat", "ramulator"):
            origin = self.root / (name + "-origin")
            origin.mkdir()
            self.git(origin, "init", "-q")
            (origin / "source.txt").write_text(name + " source fixture\n")
            self.git(origin, "add", "source.txt")
            self.git(origin, "commit", "-qm", "fixture input")
            pins[name]["revision"] = self.git(origin, "rev-parse", "HEAD").decode().strip()
            pins[name]["tree"] = self.git(origin, "rev-parse", "HEAD^{tree}").decode().strip()
            self.git(self.source, "submodule", "add", "-q", str(origin), pins[name]["path"])
        self.git(self.source, "add", ".")
        self.git(self.source, "commit", "-qm", "fixture source")
        self.revision = self.git(self.source, "rev-parse", "HEAD").decode().strip()
        self.tools = self.source / "tools"
        self.tools.mkdir()
        (self.tools / "selected-tool").write_bytes(b"prebuilt fixture bytes\n")
        tag = inventory.preflight.read_pins(self.source)[0]["TOOLCHAIN_REV"]
        toolchain_id = tag + "-" + "b" * 40
        self.args = SimpleNamespace(source_dir=self.source, workspace_dir=self.workspace,
            expected_revision=self.revision, toolchain_id=toolchain_id,
            toolchain_cache_key="Linux-toolchain-" + toolchain_id + "-lite")
        self.commands = []
        for patch in (
            mock.patch.object(prepare, "ROOT", self.source),
            mock.patch.dict(contract.PINS, pins, clear=True),
            mock.patch.object(prepare.shutil, "disk_usage", return_value=SimpleNamespace(free=15 * 2**30)),
            mock.patch.object(prepare, "available_memory_bytes", return_value=4 * 2**30),
            mock.patch.object(prepare, "run_bounded", side_effect=self.acquire),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def acquire(self, argv, cwd, environment, log, **limits):
        self.commands.append(argv)
        if "init" in argv:
            Path(argv[-1]).mkdir()
        log.write_bytes(b"synthetic acquisition observation; no remote command ran\n")
        return {"process_started": True, "outcome": "pass", "exit_code": 0,
                "reason": None, "cleanup_complete": True}

    def cache_identity(self, root):
        return {path.relative_to(root).as_posix():
                (path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
                for path in root.rglob("*") if path.is_file()}

    def run_prepare(self):
        report = prepare.prepare(self.args)
        retained = self.workspace / "evidence/dependency-preparation.json"
        self.assertEqual(report, json.loads(retained.read_bytes()))
        self.assertEqual(report["native_execution"], "not_run")
        self.assertIs(report["dependency_cache_used"], False)
        self.assertTrue(all(report[name] is False for name in contract.FALSE_CLAIMS))
        return report

    def assert_pre_move_block(self, phrase, expected):
        report = self.run_prepare()
        self.assertEqual(report["outcome"], "blocked")
        self.assertIn(phrase, report["reason"])
        self.assertEqual(self.commands, [])
        self.assertNotIn("tools_dir", report)
        self.assertEqual(self.cache_identity(self.tools), expected)
        return report

    def test_single_untracked_cache_is_relocated_before_strict_inventory(self):
        before = inventory.collect_source(self.source)
        self.assertEqual(before["outcome"], "blocked")
        self.assertIs(before["dirty"], True)
        self.assertEqual(before["untracked_paths"], ["tools/selected-tool"])
        expected = self.cache_identity(self.tools)
        report = self.run_prepare()
        self.assertEqual(report["outcome"], "pass")
        self.assertEqual(report["source_before"], report["source_after"])
        self.assertIs(report["source_before"]["dirty"], False)
        self.assertEqual(len(report["source_before"]["submodules"]["entries"]), 2)
        self.assertEqual(len(self.commands), 6)
        self.assertFalse(self.tools.exists())
        self.assertEqual(self.cache_identity(self.workspace / "tools"), expected)

    def test_large_real_git_status_retains_its_bound_and_preparation_succeeds(self):
        for index in range(2000):
            (self.tools / ("selected-compiler-support-file-" + str(index).zfill(4))).write_bytes(b"input\n")
        status = self.git(self.source, "status", "--porcelain=v1", "-z", "--untracked-files=all",
                          "--ignore-submodules=none")
        self.assertGreater(len(status), inventory.MAX_PROBE_BYTES)
        before = inventory.collect_source(self.source)
        self.assertEqual(before["outcome"], "blocked")
        self.assertIsNone(before["dirty"])
        self.assertIn("source identity could not be completely verified", before["blockers"])
        expected = self.cache_identity(self.tools)
        report = self.run_prepare()
        self.assertEqual(report["outcome"], "pass")
        self.assertEqual(report["source_before"], report["source_after"])
        self.assertEqual(report["source_before"]["outcome"], "pass")
        self.assertEqual(inventory.MAX_PROBE_BYTES, 65536)
        self.assertEqual(self.cache_identity(self.workspace / "tools"), expected)

    def test_dirty_tracked_source_is_blocked_with_cache_preserved(self):
        expected = self.cache_identity(self.tools)
        (self.source / "configure").write_bytes(b"changed source\n")
        report = self.run_prepare()
        self.assertEqual(report["outcome"], "blocked")
        self.assertIn("source contains tracked changes or nonignored untracked inputs", report["reason"])
        self.assertIn("configure", report["source_before"]["changed_paths"])
        self.assertEqual(report["tools_dir"], str(self.workspace / "tools"))
        self.assertEqual(self.cache_identity(self.workspace / "tools"), expected)
        self.assertEqual(self.commands, [])

    def test_untracked_source_outside_cache_is_not_hidden(self):
        expected = self.cache_identity(self.tools)
        (self.source / "unreviewed-input").write_bytes(b"must remain dirty\n")
        report = self.run_prepare()
        self.assertEqual(report["outcome"], "blocked")
        self.assertEqual(report["source_before"]["untracked_paths"], ["unreviewed-input"])
        self.assertEqual(self.cache_identity(self.workspace / "tools"), expected)
        self.assertEqual(self.commands, [])

    def test_wrong_revision_is_blocked_without_acquisition_and_retains_cache(self):
        expected = self.cache_identity(self.tools)
        self.args.expected_revision = "c" * 40
        report = self.run_prepare()
        self.assertEqual(report["outcome"], "blocked")
        self.assertIn("expected revision", report["reason"])
        self.assertEqual(report["source_before"]["revision"], self.revision)
        self.assertEqual(report["tools_dir"], str(self.workspace / "tools"))
        self.assertEqual(self.cache_identity(self.workspace / "tools"), expected)
        self.assertEqual(self.commands, [])

    def test_tracked_tool_input_is_never_moved(self):
        self.git(self.source, "add", "tools/selected-tool")
        expected = self.cache_identity(self.tools)
        self.assert_pre_move_block("contains tracked source", expected)
        self.assertFalse((self.workspace / "tools").exists())

    def test_symlink_cache_root_is_never_followed_or_moved(self):
        expected = self.cache_identity(self.tools)
        actual = self.root / "actual-cache"
        self.tools.rename(actual)
        self.tools.symlink_to(actual, target_is_directory=True)
        report = self.run_prepare()
        self.assertEqual(report["outcome"], "blocked")
        self.assertIn("symlink traversal", report["reason"])
        self.assertTrue(self.tools.is_symlink())
        self.assertEqual(self.cache_identity(actual), expected)
        self.assertEqual(self.commands, [])
        self.assertFalse((self.workspace / "tools").exists())

    def test_existing_relocation_target_is_preserved(self):
        expected = self.cache_identity(self.tools)
        target = self.workspace / "tools"
        target.mkdir()
        (target / "owned-input").write_bytes(b"preexisting workspace data\n")
        target_before = self.cache_identity(target)
        self.assert_pre_move_block("relocation must be fresh", expected)
        self.assertEqual(self.cache_identity(target), target_before)

    def test_bad_cache_identity_rejects_before_relocation(self):
        expected = self.cache_identity(self.tools)
        self.args.toolchain_cache_key = "Linux-toolchain-wrong-cache-lite"
        self.assert_pre_move_block("matching pinned", expected)

    def test_disk_shortfall_rejects_before_relocation(self):
        expected = self.cache_identity(self.tools)
        with mock.patch.object(prepare.shutil, "disk_usage", return_value=SimpleNamespace(free=15 * 2**30 - 1)):
            self.assert_pre_move_block("15 GiB disk reserve", expected)

    def test_memory_shortfall_rejects_before_relocation(self):
        expected = self.cache_identity(self.tools)
        with mock.patch.object(prepare, "available_memory_bytes", return_value=4 * 2**30 - 1):
            self.assert_pre_move_block("4 GiB available RAM", expected)

    def test_changed_initialized_gitlink_rejects_before_relocation(self):
        expected = self.cache_identity(self.tools)
        dependency = self.source / contract.PINS["ramulator"]["path"]
        (dependency / "source.txt").write_text("changed dependency fixture\n")
        self.git(dependency, "commit", "-qam", "unselected dependency revision")
        self.assert_pre_move_block("initialized dependency differs", expected)


if __name__ == "__main__":
    unittest.main()
