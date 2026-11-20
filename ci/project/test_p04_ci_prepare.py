# SPDX-License-Identifier: Apache-2.0
"""Host-only CI preparation guards using disposable, real Git checkouts.

Git identity, dirty-tree and submodule observations, relocation, hashes and
receipt writes are real. Resource observations and native tool inventories are
controlled because these tests neither install nor execute a GPU toolchain.
"""

from contextlib import ExitStack, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

import baseline_inventory
import p04_ci_prepare as preparation
from tensor_host_tools import run_host_command


ROOT = preparation.ROOT
PREPARATION_SOURCES = (
    "ci/project/p04_ci_prepare.py", ".github/workflows/p04-model.yml",
    "ci/toolchain_rev.sh", "ci/install_dependencies.sh",
)
TOOLCHAIN_ID = "v3.0.2-" + "a" * 40
DEPENDENCY_KEY = "Linux-thirdparty-" + "b" * 64
MARKER = b"synthetic restored cache; no native tools\n"


class TinyMlpCiPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="p04-prepare-host-", dir=ROOT.parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.template = cls.root / "template"
        cls.template.mkdir()
        cls.environment = {
            "PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": "P04 host test",
            "GIT_AUTHOR_EMAIL": "p04-test@example.invalid",
            "GIT_COMMITTER_NAME": "P04 host test",
            "GIT_COMMITTER_EMAIL": "p04-test@example.invalid",
        }
        for name in dict.fromkeys((*baseline_inventory.SOURCE_INPUTS, *PREPARATION_SOURCES)):
            target = cls.template / name
            target.parent.mkdir(parents=True, exist_ok=True)
            # No network or initialized submodules are needed for this fixture.
            target.write_bytes(b"" if name == ".gitmodules" else (ROOT / name).read_bytes())
        for name in preparation.base.DEPENDENCIES:
            target = cls.template / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"synthetic dependency identity for " + name.encode() + b"\n")
        cls.git(cls.template, "init", "--quiet")
        cls.git(cls.template, "add", ".")
        cls.git(cls.template, "commit", "--quiet", "-m", "Disposable preparation fixture")
        cls.revision = cls.git(cls.template, "rev-parse", "HEAD").strip()
        cls.identities = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                          for name in PREPARATION_SOURCES}

    @classmethod
    def git(cls, source, *arguments):
        return run_host_command(
            ["git", "-c", "maintenance.auto=false", "-c", "gc.auto=0",
             "-C", str(source), *arguments], cwd=cls.root,
            env=cls.environment, timeout=20,
        )

    def setUp(self):
        self.scenarios = 0
        self.test_directory = Path(tempfile.mkdtemp(prefix="scenario-", dir=self.root))

    def tearDown(self):
        for name, identity in self.identities.items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), identity,
                             "a preparation input changed during host validation: " + name)

    def fixture(self):
        self.scenarios += 1
        parent = self.test_directory / str(self.scenarios)
        parent.mkdir()
        source = parent / "source"
        shutil.copytree(self.template, source)
        workspace = parent / "workspace"
        workspace.mkdir()
        (source / "tools").mkdir()
        (source / "tools/marker").write_bytes(MARKER)
        return SimpleNamespace(source=source, workspace=workspace, args=SimpleNamespace(
            source_dir=source, workspace_dir=workspace, expected_revision=self.revision,
            toolchain_id=TOOLCHAIN_ID,
            toolchain_cache_key="Linux-toolchain-" + TOOLCHAIN_ID + "-lite",
            third_party_cache_key=DEPENDENCY_KEY, expected_third_party_key=DEPENDENCY_KEY,
            backend="simx", format="both",
        ))

    def controlled_environment(self, fixture, *, memory=preparation.MAX_RSS_BYTES,
                               disk=None, inventory=None):
        stack = ExitStack()
        stack.enter_context(mock.patch.object(preparation, "ROOT", fixture.source))
        stack.enter_context(mock.patch.object(preparation, "available_memory_bytes", return_value=memory))
        disk = disk or (lambda _: SimpleNamespace(free=preparation.MIN_FREE_BYTES))
        stack.enter_context(mock.patch.object(preparation.shutil, "disk_usage", side_effect=disk))
        inventory = inventory or (lambda paths, env, backends: {
            "host_only_mock": True, "backends": backends,
            "marker": baseline_inventory.hash_artifacts(paths["tools"], ["marker"]),
        })
        probe = stack.enter_context(mock.patch.object(preparation.base, "tool_inventory", side_effect=inventory))
        return stack, probe

    def prepare(self, fixture, **options):
        stack, probe = self.controlled_environment(fixture, **options)
        with stack:
            report = preparation.prepare(fixture.args)
        self.assertEqual(json.loads((fixture.workspace / "evidence/preparation.json").read_text()), report)
        self.assertEqual(report["native_execution"], "not_run")
        self.assertIs(report["acceptance_claimed"], False)
        return report, probe

    def blocked(self, fixture, reason, *, moved=False, **options):
        report, probe = self.prepare(fixture, **options)
        self.assertEqual(report["outcome"], "blocked")
        self.assertIn(reason, report["reason"])
        self.assertEqual(report["tools_relocated"], moved)
        location = fixture.workspace if moved else fixture.source
        self.assertEqual((location / "tools/marker").read_bytes(), MARKER)
        return report, probe

    def test_exact_resource_boundary_and_both_cache_profiles_preserve_real_identities(self):
        for profile, backend, format_name in (("lite", "simx", "both"), ("full", "rtlsim", "bf16")):
            with self.subTest(profile=profile):
                fixture = self.fixture()
                fixture.args.toolchain_cache_key = "Linux-toolchain-" + TOOLCHAIN_ID + "-" + profile
                fixture.args.backend, fixture.args.format = backend, format_name
                inode = (fixture.source / "tools/marker").stat().st_ino
                report, probe = self.prepare(fixture)
                self.assertEqual(report["outcome"], "pass", report["reason"])
                self.assertTrue(report["tools_relocated"])
                self.assertFalse((fixture.source / "tools").exists())
                self.assertEqual((fixture.workspace / "tools/marker").stat().st_ino, inode)
                self.assertEqual(report["source"]["revision"], self.revision)
                self.assertIs(report["source"]["dirty"], False)
                self.assertEqual(report["source"]["blockers"], [])
                self.assertEqual(report["formats"], ["fp16", "bf16"] if format_name == "both" else [format_name])
                self.assertEqual(report["dependency_identities"], baseline_inventory.hash_artifacts(
                    fixture.source, preparation.base.DEPENDENCIES))
                self.assertEqual(report["preparation_sources"], baseline_inventory.hash_artifacts(
                    fixture.source, PREPARATION_SOURCES))
                self.assertNotIn("HOME", probe.call_args.args[1])
                self.assertEqual(probe.call_args.args[1]["MAKEFLAGS"], "-j2")
                self.assertEqual(probe.call_args.args[2], [backend])

    def test_missing_or_mismatched_cache_bindings_block_before_relocation(self):
        for key, value, reason in (
            ("toolchain_id", "v0.0.0-" + "a" * 40, "differs from VERSION"),
            ("toolchain_id", "v3.0.2-" + "A" * 40, "differs from VERSION"),
            ("toolchain_cache_key", "", "matching pinned toolchain cache"),
            ("toolchain_cache_key", "Linux-toolchain-" + TOOLCHAIN_ID + "-debug", "matching pinned toolchain cache"),
            ("third_party_cache_key", "Linux-thirdparty-" + "c" * 64, "matching dependency cache"),
            ("expected_third_party_key", "Linux-thirdparty-short", "matching dependency cache"),
        ):
            with self.subTest(key=key, value=value):
                fixture = self.fixture()
                setattr(fixture.args, key, value)
                report, probe = self.blocked(fixture, reason)
                probe.assert_not_called()
                if "cache is unavailable" in report["reason"]:
                    self.assertIn(preparation.CACHE_REMEDY, report["reason"])

    def test_invalid_pins_and_source_revisions_cannot_move_cache_tools(self):
        for mode in ("invalid_pins", "malformed_revision", "different_head"):
            with self.subTest(mode=mode):
                fixture = self.fixture()
                if mode == "invalid_pins":
                    (fixture.source / "VERSION").write_text("TOOLCHAIN_REV=missing-other-pins\n")
                    reason = "invalid VERSION pins"
                else:
                    fixture.args.expected_revision = "bad" if mode == "malformed_revision" else "f" * 40
                    reason = "invalid source revision" if mode == "malformed_revision" else "before relocation"
                _, probe = self.blocked(fixture, reason)
                probe.assert_not_called()

    def test_unknown_or_insufficient_resources_block_before_relocation(self):
        for mode in ("source_disk", "workspace_disk", "low_memory", "unknown_memory"):
            with self.subTest(mode=mode):
                fixture = self.fixture()
                selected = fixture.source if mode == "source_disk" else fixture.workspace
                options = {}
                if mode.endswith("disk"):
                    options["disk"] = lambda path: SimpleNamespace(
                        free=preparation.MIN_FREE_BYTES - int(path == selected))
                    reason = "disk reserve below 15 GiB"
                else:
                    options["memory"] = None if mode == "unknown_memory" else preparation.MAX_RSS_BYTES - 1
                    reason = "need 4 GiB available RAM"
                _, probe = self.blocked(fixture, reason, **options)
                probe.assert_not_called()

    def test_existing_destinations_and_symlinked_tools_are_preserved(self):
        for kind in ("directory", "file", "dangling_symlink", "source_symlink"):
            with self.subTest(kind=kind):
                fixture = self.fixture()
                target = fixture.workspace / "tools"
                if kind == "directory":
                    target.mkdir()
                    (target / "preserved").write_bytes(b"existing")
                elif kind == "file":
                    target.write_bytes(b"existing")
                elif kind == "dangling_symlink":
                    target.symlink_to(fixture.workspace / "missing")
                else:
                    actual = fixture.source.parent / "actual-tools"
                    (fixture.source / "tools").rename(actual)
                    (fixture.source / "tools").symlink_to(actual, target_is_directory=True)
                _, probe = self.blocked(fixture, "symlink traversal" if kind == "source_symlink" else "must be fresh")
                probe.assert_not_called()
                if kind == "directory":
                    self.assertEqual((target / "preserved").read_bytes(), b"existing")
                elif kind == "file":
                    self.assertEqual(target.read_bytes(), b"existing")
                elif kind == "dangling_symlink":
                    self.assertTrue(target.is_symlink())

    def test_workspace_and_evidence_symlinks_are_rejected_without_receipts(self):
        for mode in ("nested", "workspace_symlink", "evidence_symlink"):
            with self.subTest(mode=mode):
                fixture = self.fixture()
                if mode == "nested":
                    fixture.args.workspace_dir = fixture.source / "nested"
                    fixture.args.workspace_dir.mkdir()
                elif mode == "workspace_symlink":
                    fixture.args.workspace_dir = fixture.source.parent / "workspace-link"
                    fixture.args.workspace_dir.symlink_to(fixture.workspace, target_is_directory=True)
                else:
                    elsewhere = fixture.source.parent / "elsewhere"
                    elsewhere.mkdir()
                    (fixture.workspace / "evidence").symlink_to(elsewhere, target_is_directory=True)
                stack, probe = self.controlled_environment(fixture)
                with stack, self.assertRaises(ValueError):
                    preparation.prepare(fixture.args)
                probe.assert_not_called()
                self.assertEqual((fixture.source / "tools/marker").read_bytes(), MARKER)
                self.assertFalse((fixture.workspace / "evidence/preparation.json").exists())

    def test_tracked_tools_are_not_relocated(self):
        fixture = self.fixture()
        self.git(fixture.source, "add", "tools/marker")
        self.git(fixture.source, "commit", "--quiet", "-m", "Tracked tools guard")
        fixture.args.expected_revision = self.git(fixture.source, "rev-parse", "HEAD").strip()
        _, probe = self.blocked(fixture, "refusing to relocate tracked source files")
        probe.assert_not_called()

    def test_real_dirty_source_blocks_after_preserving_relocated_tools(self):
        for mode in ("tracked", "untracked"):
            with self.subTest(mode=mode):
                fixture = self.fixture()
                target = fixture.source / ("configure" if mode == "tracked" else "unexpected-input")
                target.write_bytes(target.read_bytes() + b"\nchanged\n" if target.exists() else b"untracked\n")
                report, probe = self.blocked(fixture, "source or recursive submodule provenance", moved=True)
                self.assertTrue(report["source"]["dirty"])
                probe.assert_not_called()

    def test_real_uninitialized_submodule_blocks_after_relocation(self):
        fixture = self.fixture()
        (fixture.source / ".gitmodules").write_text(
            '[submodule "unit-fixture"]\n\tpath = third_party/unit-fixture\n\turl = ../unit-fixture\n')
        self.git(fixture.source, "add", ".gitmodules")
        self.git(fixture.source, "update-index", "--add", "--cacheinfo",
                 "160000," + self.revision + ",third_party/unit-fixture")
        self.git(fixture.source, "commit", "--quiet", "-m", "Uninitialized submodule guard")
        fixture.args.expected_revision = self.git(fixture.source, "rev-parse", "HEAD").strip()
        report, probe = self.blocked(fixture, "submodule is not at its recorded revision", moved=True)
        self.assertEqual(report["source"]["submodules"]["entries"][0]["status"], "not_initialized")
        probe.assert_not_called()

    def test_checkout_moved_between_precheck_and_inventory_is_rejected(self):
        fixture = self.fixture()
        collect = preparation.collect_source

        def change_then_observe(source):
            (source / "configure").write_bytes(b"changed after relocation\n")
            self.git(source, "add", "configure")
            self.git(source, "commit", "--quiet", "-m", "Source drift guard")
            return collect(source)

        with mock.patch.object(preparation, "collect_source", side_effect=change_then_observe):
            report, probe = self.blocked(fixture, "checkout differs from the workflow SHA", moved=True)
        self.assertNotEqual(report["source"]["revision"], fixture.args.expected_revision)
        probe.assert_not_called()

    def test_cross_filesystem_relocation_is_blocked_without_copy(self):
        fixture = self.fixture()
        original_stat = Path.stat

        def different_device(path, *arguments, **keywords):
            observed = original_stat(path, *arguments, **keywords)
            if path == fixture.workspace:
                values = list(observed)
                values[2] += 1  # st_dev; all ordinary directory checks still use real metadata.
                return os.stat_result(values)
            return observed

        with mock.patch.object(Path, "stat", different_device), mock.patch.object(Path, "rename") as rename:
            _, probe = self.blocked(fixture, "atomic tool relocation requires")
        rename.assert_not_called()
        probe.assert_not_called()

    def test_failed_inventory_or_missing_dependency_retains_blocked_receipt(self):
        fixture = self.fixture()

        def unavailable(*_):
            raise ValueError("synthetic tool identity unavailable")

        self.blocked(fixture, "tool identity unavailable", moved=True, inventory=unavailable)
        fixture = self.fixture()
        dependency = fixture.source / preparation.base.DEPENDENCIES[0]
        dependency.unlink()
        self.git(fixture.source, "add", str(dependency.relative_to(fixture.source)))
        self.git(fixture.source, "commit", "--quiet", "-m", "Missing dependency guard")
        fixture.args.expected_revision = self.git(fixture.source, "rev-parse", "HEAD").strip()
        self.blocked(fixture, "artifact is missing or unreadable", moved=True)

    def test_cli_cache_failure_is_nonzero_and_cannot_overwrite_evidence(self):
        fixture = self.fixture()
        fixture.args.toolchain_cache_key = "missing-cache"
        argv = [item for key, value in vars(fixture.args).items()
                for item in ("--" + key.replace("_", "-"), str(value))]
        stack, probe = self.controlled_environment(fixture)
        first = io.StringIO()
        with stack, redirect_stdout(first):
            self.assertEqual(preparation.main(argv), 1)
        self.assertEqual(json.loads(first.getvalue())["outcome"], "blocked")
        receipt = fixture.workspace / "evidence/preparation.json"
        before = receipt.read_bytes(), receipt.stat().st_mtime_ns
        stack, _ = self.controlled_environment(fixture)
        second = io.StringIO()
        with stack, redirect_stdout(second):
            self.assertEqual(preparation.main(argv), 1)
        self.assertIn("preparation receipt already exists", json.loads(second.getvalue())["reason"])
        self.assertEqual((receipt.read_bytes(), receipt.stat().st_mtime_ns), before)
        self.assertEqual((fixture.source / "tools/marker").read_bytes(), MARKER)
        probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
