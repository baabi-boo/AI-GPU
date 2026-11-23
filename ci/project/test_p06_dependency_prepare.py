# SPDX-License-Identifier: Apache-2.0
"""Exercise preparation admission and retained failures without downloading tools."""

import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import p06_dependency_contract as contract
import p06_dependency_prepare as prepare


class DependencyPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p06-prepare-controls-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source, self.workspace = self.root / "source", self.root / "workspace"
        self.source.mkdir()
        self.workspace.mkdir()
        for name in ("softfloat", "ramulator"):
            (self.source / contract.PINS[name]["path"]).mkdir(parents=True, exist_ok=True)
        self.tools = self.source / "tools"
        self.tools.mkdir()
        (self.tools / "selected-tool").write_bytes(b"prebuilt identity\n")
        self.revision = "a" * 40
        self.checkout = {"revision": self.revision, "dirty": False, "blockers": []}
        self.args = SimpleNamespace(source_dir=self.source, workspace_dir=self.workspace,
            expected_revision=self.revision, toolchain_id="v3.0.2-" + "b" * 40,
            toolchain_cache_key="Linux-toolchain-v3.0.2-" + "b" * 40 + "-lite")
        self.observed = []
        self.git_status = b""
        self.patches = [
            mock.patch.object(prepare, "ROOT", self.source),
            mock.patch.object(prepare, "collect_source", side_effect=lambda root: copy.deepcopy(self.checkout)),
            mock.patch.object(prepare, "read_pins", return_value=({"TOOLCHAIN_REV": "v3.0.2"}, [])),
            mock.patch.object(prepare.shutil, "disk_usage", return_value=SimpleNamespace(free=15 * 2**30)),
            mock.patch.object(prepare, "available_memory_bytes", return_value=4 * 2**30),
            mock.patch.object(prepare, "_git", side_effect=self.git),
            mock.patch.object(prepare, "run_bounded", side_effect=self.command),
        ]
        self.mocks = [patch.start() for patch in self.patches]
        for patch in self.patches:
            self.addCleanup(patch.stop)

    def git(self, root, *args):
        if args[:3] == ("ls-tree", "-z", "HEAD"):
            pin = next(row for row in contract.PINS.values() if row["path"] == args[-1])
            return ("160000 commit " + pin["revision"] + "\t" + pin["path"] + "\0").encode()
        if args == ("rev-parse", "HEAD"):
            name = next(name for name in ("softfloat", "ramulator")
                        if root == self.source / contract.PINS[name]["path"])
            return (contract.PINS[name]["revision"] + "\n").encode()
        if args == ("status", "--porcelain=v1", "--untracked-files=all", "--ignored"):
            return self.git_status
        if args == ("ls-files", "-z", "--", "tools"):
            return b""
        raise AssertionError("Unexpected Git observation: " + repr(args))

    def command(self, argv, cwd, environment, log, **limits):
        self.observed.append((argv, cwd, dict(environment), limits))
        if "init" in argv:
            Path(argv[-1]).mkdir()
        log.write_text("synthetic acquisition control\n")
        return {"process_started": True, "outcome": "pass", "exit_code": 0,
                "reason": None, "cleanup_complete": True}

    def run_prepare(self):
        report = prepare.prepare(self.args)
        self.assertEqual(report, json.loads(
            (self.workspace / "evidence/dependency-preparation.json").read_text()))
        self.assertIs(report["dependency_cache_used"], False)
        self.assertEqual(report["native_execution"], "not_run")
        self.assertTrue(all(report[name] is False for name in contract.FALSE_CLAIMS))
        return report

    def test_fresh_exact_acquisition_preserves_pins_and_fixed_command_bounds(self):
        report = self.run_prepare()
        self.assertEqual(report["outcome"], "pass")
        self.assertEqual(set(report["repositories"]), set(contract.PINS))
        self.assertEqual(report["source_before"], report["source_after"])
        self.assertEqual(len(self.observed), 6)
        self.assertFalse(self.tools.exists())
        self.assertEqual((self.workspace / "tools/selected-tool").read_bytes(), b"prebuilt identity\n")
        fetches = [row for row in self.observed if "fetch" in row[0]]
        self.assertEqual([(row[0][-2], row[0][-1]) for row in fetches],
                         [(contract.PINS[name]["url"], contract.PINS[name]["revision"])
                          for name in ("yaml-cpp", "spdlog", "argparse")])
        for argv, cwd, environment, limits in self.observed:
            self.assertEqual(limits, {"timeout_seconds": 120,
                "min_free_bytes": 15 * 2**30, "max_rss_bytes": 4 * 2**30,
                "max_log_bytes": 16 * 2**20, "resource_paths": (self.source, self.workspace)})
            self.assertIn("core.hooksPath=/dev/null", argv)
            self.assertEqual(environment["GIT_CONFIG_GLOBAL"], "/dev/null")
            self.assertEqual(environment["GIT_CONFIG_NOSYSTEM"], "1")
            self.assertEqual(environment["GIT_TERMINAL_PROMPT"], "0")
        self.assertNotIn("environment", report)

    def test_full_pinned_toolchain_cache_is_also_supported(self):
        self.args.toolchain_cache_key = self.args.toolchain_cache_key.removesuffix("lite") + "full"
        self.assertEqual(self.run_prepare()["outcome"], "pass")

    def test_wrong_source_revision_is_retained_before_any_move_or_command(self):
        self.args.expected_revision = "c" * 40
        report = self.run_prepare()
        self.assertEqual(report["outcome"], "blocked")
        self.assertIn("expected revision", report["reason"])
        self.assertTrue(self.tools.exists())
        self.assertEqual(self.observed, [])

    def test_invalid_revision_is_retained_before_source_observation(self):
        self.args.expected_revision = "HEAD"
        self.assertIn("exact source revision", self.run_prepare()["reason"])
        self.mocks[1].assert_not_called()

    def test_dirty_source_is_never_prepared(self):
        self.checkout["dirty"] = True
        self.assertIn("clean source", self.run_prepare()["reason"])
        self.assertTrue(self.tools.exists())

    def test_missing_cache_is_retained_and_does_not_rebuild_toolchain(self):
        self.args.toolchain_cache_key = ""
        self.assertIn("matching pinned", self.run_prepare()["reason"])
        self.assertTrue(self.tools.exists())
        self.assertEqual(self.observed, [])

    def test_mismatched_version_tag_is_rejected(self):
        self.args.toolchain_id = "other-" + "b" * 40
        self.assertIn("differs from VERSION", self.run_prepare()["reason"])

    def test_disk_reserve_cannot_be_waived_by_cache_availability(self):
        self.mocks[3].return_value = SimpleNamespace(free=15 * 2**30 - 1)
        report = self.run_prepare()
        self.assertIn("15 GiB disk reserve", report["reason"])
        self.assertEqual(self.observed, [])
        self.assertTrue(self.tools.exists())

    def test_memory_reserve_cannot_be_waived_by_cache_availability(self):
        self.mocks[4].return_value = 4 * 2**30 - 1
        self.assertIn("4 GiB available RAM", self.run_prepare()["reason"])
        self.assertEqual(self.observed, [])

    def test_ignored_submodule_cache_is_rejected_before_relocation(self):
        self.git_status = b"!! build/CMakeCache.txt\n"
        self.assertIn("changed, untracked or ignored", self.run_prepare()["reason"])
        self.assertTrue(self.tools.exists())
        self.assertEqual(self.observed, [])

    def test_cached_selected_product_is_rejected_even_when_status_omits_it(self):
        product = self.source / contract.PRODUCTS["ramulator"]
        product.write_bytes(b"favorable cached library")
        self.assertIn("pre-existing dependency product", self.run_prepare()["reason"])
        self.assertEqual(product.read_bytes(), b"favorable cached library")
        self.assertEqual(self.observed, [])

    def test_prepopulated_fetched_sources_are_rejected(self):
        (self.source / contract.PINS["yaml-cpp"]["path"]).mkdir(parents=True)
        self.assertIn("pre-existing fetched", self.run_prepare()["reason"])
        self.assertTrue(self.tools.exists())

    def test_preexisting_acquisition_root_rejects_before_toolchain_move(self):
        (self.workspace / "dependency-acquisition").mkdir()
        self.assertIn("acquisition workspace must be fresh", self.run_prepare()["reason"])
        self.assertTrue(self.tools.exists())

    def test_preexisting_logs_reject_before_toolchain_move(self):
        (self.workspace / "evidence/dependency-acquisition-logs").mkdir(parents=True)
        self.assertIn("acquisition logs must be fresh", self.run_prepare()["reason"])
        self.assertTrue(self.tools.exists())

    def test_failed_acquisition_stops_at_first_command_and_retains_failure(self):
        def failed(*args, **kwargs):
            result = self.command(*args, **kwargs)
            return dict(result, outcome="fail", exit_code=17, reason="git fetch failed")
        self.mocks[6].side_effect = failed
        report = self.run_prepare()
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual(len(report["commands"]), 1)
        self.assertEqual(report["commands"][0]["reason"], "git fetch failed")
        self.assertEqual(len(report["failures"]), 1)
        self.assertIn("yaml-cpp-init", report["reason"])

    def test_exit_zero_with_failure_reason_is_not_success(self):
        def inconsistent(*args, **kwargs):
            return dict(self.command(*args, **kwargs), reason="monitor failed")
        self.mocks[6].side_effect = inconsistent
        self.assertEqual(self.run_prepare()["outcome"], "fail")
        self.assertEqual(len(self.observed), 1)

    def test_keyboard_interrupt_is_retained_without_success_or_empty_reason(self):
        def interrupted(*args, **kwargs):
            if self.observed:
                raise KeyboardInterrupt()
            return self.command(*args, **kwargs)
        self.mocks[6].side_effect = interrupted
        report = self.run_prepare()
        self.assertEqual((report["outcome"], report["reason"]), ("fail", "interrupted"))
        self.assertEqual(len(report["commands"]), 2)
        self.assertEqual(report["failures"], [{"stage": "preparation", "reason": "interrupted"}])

    def test_post_acquisition_source_mutation_rejects_the_attempt(self):
        self.mocks[1].side_effect = [copy.deepcopy(self.checkout), dict(self.checkout, dirty=True)]
        report = self.run_prepare()
        self.assertEqual(report["outcome"], "fail")
        self.assertIn("source changed", report["reason"])

    def test_preparation_receipt_is_exclusive(self):
        self.run_prepare()
        original = (self.workspace / "evidence/dependency-preparation.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "receipt already exists"):
            prepare.prepare(self.args)
        self.assertEqual((self.workspace / "evidence/dependency-preparation.json").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
