# Licensed under the Apache License, Version 2.0.
"""Independent XRT source regressions using only disposable local Git repositories."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import baseline_inventory
import xrt_inventory
import xrt_source
from xrt_test_support import VendorFixture


def git(root, *arguments):
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.run(
        ["git", "--no-optional-locks", "-C", str(root),
         "-c", "user.name=XRT Source Fixture", "-c", "user.email=fixture@example.invalid",
         "-c", "commit.gpgsign=false", *arguments],
        env=environment, check=True, capture_output=True, timeout=10,
    ).stdout


def write(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def create_repository(root, source=False):
    root.mkdir(parents=True, exist_ok=True)
    write(root / "ordinary-input.txt", "committed fixture input\n")
    if source:
        for relative in ("configure", "config.mk.in", "VX_config.toml", "VX_types.toml",
                         "ci/gen_config.py", "ci/blackbox.sh"):
            write(root / relative, "inert committed source\n")
        write(root / ".gitmodules", "")
        write(root / "VERSION", "VORTEX_VERSION=3.0\nTOOLCHAIN_REV=v3.0.2\n"
              "GEM5_REV=v25.0.0.1\nFIRESIM_REV=57bb93f1e23daf46198659ddd93608f70121fee0\n")
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "commit", "-qm", "inert local fixture")


def index_snapshot(root):
    path = Path(os.fsdecode(git(root, "rev-parse", "--git-path", "index")).strip())
    if not path.is_absolute():
        path = root / path
    metadata = path.stat()
    return path.read_bytes(), metadata.st_mtime_ns, metadata.st_ctime_ns


class SourceFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "source"
        create_repository(self.root, source=True)

    def assertBlocked(self, report, reason):
        self.assertEqual(report["outcome"], "blocked", report)
        self.assertTrue(any(reason in item for item in report["blockers"]), report)


class SourceProvenanceTests(SourceFixture):
    def test_clean_source_preserves_native_identity_and_does_not_write_index(self):
        before = index_snapshot(self.root)
        report = xrt_source.collect_source(self.root)
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(report["revision"], git(self.root, "rev-parse", "HEAD").decode().strip())
        self.assertTrue(report["index_flags"]["verified"])
        self.assertEqual(report["index_flags"]["repositories"][0]["path"], ".")
        self.assertEqual(index_snapshot(self.root), before)

    def test_hidden_configure_change_is_blocked_for_each_index_flag(self):
        for flag in ("skip-worktree", "assume-unchanged"):
            with self.subTest(flag=flag):
                root = self.base / flag
                create_repository(root, source=True)
                git(root, "update-index", "--" + flag, "configure")
                write(root / "configure", "modified bytes hidden from Git status\n")
                self.assertNotEqual((root / "configure").read_bytes(), git(root, "show", "HEAD:configure"))
                self.assertEqual(git(root, "status", "--porcelain=v1", "-z"), b"")
                self.assertEqual(baseline_inventory.collect_source(root)["outcome"], "pass")
                before = index_snapshot(root)
                report = xrt_source.collect_source(root)
                self.assertBlocked(report, flag)
                self.assertIs(report["dirty"], False)
                self.assertFalse(report["index_flags"]["verified"])
                self.assertEqual(index_snapshot(root), before)

    def test_flags_on_unchanged_inputs_outside_native_hash_list_are_blocked(self):
        for flag in ("skip-worktree", "assume-unchanged"):
            with self.subTest(flag=flag):
                git(self.root, "update-index", "--" + flag, "ordinary-input.txt")
                self.assertBlocked(xrt_source.collect_source(self.root), flag)
                git(self.root, "update-index", "--no-" + flag, "ordinary-input.txt")

    def test_both_index_flags_are_identified(self):
        for flag in ("skip-worktree", "assume-unchanged"):
            git(self.root, "update-index", "--" + flag, "configure")
        report = xrt_source.collect_source(self.root)
        self.assertBlocked(report, "skip-worktree and assume-unchanged")

    def test_manifest_inspection_uses_the_real_source_check(self):
        fixture = VendorFixture(self.base / "vendor-fixture")
        create_repository(fixture.source, source=True)
        fixture.manifest["source"] = {
            "revision": git(fixture.source, "rev-parse", "HEAD").decode().strip(),
            "tree": git(fixture.source, "rev-parse", "HEAD^{tree}").decode().strip(),
        }
        fixture.refresh(bind_receipt=True)
        report = xrt_inventory.inspect_manifest(fixture.manifest, fixture.source)
        self.assertEqual(report["outcome"], "pass", report)
        git(fixture.source, "update-index", "--skip-worktree", "configure")
        write(fixture.source / "configure", "hidden replacement configure\n")
        report = xrt_inventory.inspect_manifest(fixture.manifest, fixture.source)
        self.assertBlocked(report, "skip-worktree")
        self.assertEqual(report["acceptance"], "not_evaluated")

    def test_large_clean_index_is_scanned_past_the_native_probe_limit(self):
        for index in range(700):
            write(self.root / "many" / (str(index).zfill(4) + "-" + "x" * 100), "")
        last = "zz-final-input.txt"
        write(self.root / last, "original\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "bounded larger index fixture")
        output = git(self.root, "ls-files", "--cached", "--stage", "-v", "-z")
        self.assertGreater(len(output), 65536)
        report = xrt_source.collect_source(self.root)
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(report["index_flags"]["repositories"][0]["size_bytes"], len(output))
        git(self.root, "update-index", "--assume-unchanged", last)
        write(self.root / last, "hidden edit at end of index\n")
        self.assertBlocked(xrt_source.collect_source(self.root), last)

    def test_index_limits_block_instead_of_accepting_a_partial_scan(self):
        for constant, value, reason in (("MAX_INDEX_BYTES", 64, "byte limit"),
                                        ("MAX_RECORD_BYTES", 16, "record"),
                                        ("INDEX_TIMEOUT_SECONDS", 0, "timed out")):
            with self.subTest(constant=constant), mock.patch.object(xrt_source, constant, value):
                before = index_snapshot(self.root)
                self.assertBlocked(xrt_source.collect_source(self.root), reason)
                self.assertEqual(index_snapshot(self.root), before)

    def test_nul_delimiters_preserve_unusual_clean_tracked_filenames(self):
        write(self.root / "space and\ttab.txt", "inert\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "unusual tracked filename")
        report = xrt_source.collect_source(self.root)
        self.assertEqual(report["outcome"], "pass", report)

    def test_nonrepository_and_subdirectory_are_blocked(self):
        for root in (self.base, self.root / "ci"):
            with self.subTest(root=root):
                report = xrt_source.collect_source(root)
                self.assertBlocked(report, "checkout root")
                self.assertFalse(report["index_flags"]["verified"])


class SubmoduleProvenanceTests(SourceFixture):
    def setUp(self):
        super().setUp()
        leaf = self.base / "leaf-origin"
        middle = self.base / "middle-origin"
        create_repository(leaf)
        create_repository(middle)
        git(middle, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(leaf), "nested")
        git(middle, "commit", "-qam", "pin local nested fixture")
        git(self.root, "-c", "protocol.file.allow=always", "submodule", "add", "-q",
            str(middle), "third_party/dependency")
        git(self.root, "commit", "-qam", "pin local dependency fixture")
        git(self.root, "-c", "protocol.file.allow=always", "submodule", "update", "--init", "--recursive")
        self.middle = self.root / "third_party/dependency"
        self.leaf = self.middle / "nested"

    def test_initialized_recursive_indexes_are_read_without_modification(self):
        before = {root: index_snapshot(root) for root in (self.root, self.middle, self.leaf)}
        report = xrt_source.collect_source(self.root)
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual([item["path"] for item in report["index_flags"]["repositories"]],
                         [".", "third_party/dependency", "third_party/dependency/nested"])
        self.assertEqual({root: index_snapshot(root) for root in before}, before)

    def test_hidden_changes_in_direct_and_nested_submodules_are_blocked(self):
        for root in (self.middle, self.leaf):
            for flag in ("skip-worktree", "assume-unchanged"):
                with self.subTest(root=root, flag=flag):
                    path = root / "ordinary-input.txt"
                    original = path.read_bytes()
                    git(root, "update-index", "--" + flag, path.name)
                    write(path, "hidden submodule source change\n")
                    self.assertEqual(git(self.root, "status", "--porcelain=v1", "-z",
                                         "--ignore-submodules=none"), b"")
                    report = xrt_source.collect_source(self.root)
                    self.assertBlocked(report, flag)
                    self.assertBlocked(report, path.relative_to(self.root).as_posix())
                    path.write_bytes(original)
                    git(root, "update-index", "--no-" + flag, path.name)

    def test_inactive_submodule_still_has_its_index_checked(self):
        git(self.root, "config", "submodule.third_party/dependency.active", "false")
        git(self.leaf, "update-index", "--skip-worktree", "ordinary-input.txt")
        report = xrt_source.collect_source(self.root)
        self.assertBlocked(report, "skip-worktree")
        self.assertFalse(report["index_flags"]["verified"])

    def test_flag_on_the_gitlink_itself_is_blocked(self):
        git(self.root, "update-index", "--assume-unchanged", "third_party/dependency")
        self.assertBlocked(xrt_source.collect_source(self.root), "assume-unchanged")

    def test_recursive_scan_limits_are_enforced(self):
        for constant, value, reason in (("MAX_REPOSITORIES", 2, "repository limit"),
                                        ("MAX_SUBMODULE_DEPTH", 1, "depth limit")):
            with self.subTest(constant=constant), mock.patch.object(xrt_source, constant, value):
                report = xrt_source.collect_source(self.root)
                self.assertBlocked(report, reason)
                self.assertFalse(report["index_flags"]["verified"])

    def test_missing_submodule_checkout_cannot_pass_index_verification(self):
        git(self.root, "submodule", "deinit", "-q", "-f", "third_party/dependency")
        report = xrt_source.collect_source(self.root)
        self.assertBlocked(report, "not an initialized checkout root")
        self.assertFalse(report["index_flags"]["verified"])


if __name__ == "__main__":
    unittest.main()
