# SPDX-License-Identifier: Apache-2.0
"""Required source membership checks use disposable local Git repositories."""

import json
from pathlib import Path
import tempfile
import unittest

import hwemu_inventory as inventory
import hwemu_source as source
import test_baseline_inventory as fixtures


REQUIRED_FILES = (
    "VERSION", ".gitmodules", "configure", "config.mk.in", "VX_config.toml",
    "VX_types.toml", "ci/gen_config.py", "ci/blackbox.sh",
    "sw/kernel/Makefile", "sw/runtime/stub/Makefile", "sw/runtime/common.mk",
    "sw/runtime/xrt/Makefile", "sw/runtime/xrt/xrt.ini.in",
    "tests/regression/demo/Makefile", "tests/regression/common.mk",
    "hw/syn/xilinx/xrt/Makefile", "hw/syn/xilinx/common.mk",
    "hw/syn/xilinx/platform.mk", "sw/runtime/xrt/xsim.tcl",
)
REPRESENTATIVE_FILES = ("VERSION", "sw/kernel/Makefile", "sw/runtime/xrt/xsim.tcl")


class RequiredSourceMembershipTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.new_source("source")

    def new_source(self, name):
        root = self.base / name
        fixtures.populate_source(root)
        for relative in REQUIRED_FILES:
            if not (root / relative).exists():
                fixtures.write(root / relative, "inert source fixture\n")
        (root / "configure").chmod(0o755)
        fixtures.git(root, "init", "-q", "--template=")
        fixtures.git(root, "add", ".")
        fixtures.git(root, "commit", "-qm", "inert required-source fixture")
        return root

    def remove_membership(self, root, relative, *, ignored):
        fixtures.git(root, "rm", "--cached", "--", relative)
        if ignored:
            with (root / ".gitignore").open("a", encoding="utf-8") as stream:
                stream.write("/" + relative + "\n")
            fixtures.git(root, "add", ".gitignore")
        fixtures.git(root, "commit", "-qm", "remove required source membership")
        self.assertTrue((root / relative).is_file())

    def assert_membership_blocked(self, root):
        report = source.collect_source(root)
        self.assertEqual(report["outcome"], "blocked", report)
        self.assertTrue(report["blockers"])
        self.assertIsNone(report["revision"])
        self.assertIsNone(report["tree"])
        self.assertEqual(report["pins"], {})
        self.assertEqual(report["inputs"], [])
        return report

    def test_required_regular_blobs_and_ignored_generated_output_pass(self):
        fixtures.write(self.root / "build64/generated.o", "ignored output\n")
        report = inventory.observe_source(self.root)
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(report["revision"], fixtures.git(self.root, "rev-parse", "HEAD"))
        self.assertEqual(report["tree"], fixtures.git(self.root, "rev-parse", "HEAD^{tree}"))
        self.assertIs(report["dirty"], False)
        self.assertTrue(report["clean"])

    def test_each_required_input_blocks_when_ignored_and_untracked(self):
        for index, relative in enumerate(REQUIRED_FILES):
            with self.subTest(relative=relative):
                root = self.new_source("ignored-" + str(index))
                self.remove_membership(root, relative, ignored=True)
                self.assertEqual(fixtures.git(root, "status", "--porcelain"), "")
                self.assert_membership_blocked(root)

    def test_version_missing_from_commit_blocks_public_observation(self):
        self.remove_membership(self.root, "VERSION", ignored=True)
        report = inventory.observe_source(self.root)
        self.assertEqual(report["outcome"], "blocked", report)
        self.assertFalse(report["clean"])
        self.assertIsNone(report["revision"])
        self.assertIsNone(report["tree"])
        self.assertNotIn(str(self.base), json.dumps(report))

    def test_nonignored_required_input_blocks_when_untracked(self):
        for index, relative in enumerate(REPRESENTATIVE_FILES):
            with self.subTest(relative=relative):
                root = self.new_source("untracked-" + str(index))
                self.remove_membership(root, relative, ignored=False)
                self.assert_membership_blocked(root)

    def test_staged_only_required_input_does_not_establish_head_membership(self):
        for index, relative in enumerate(REPRESENTATIVE_FILES):
            with self.subTest(relative=relative):
                root = self.new_source("staged-only-" + str(index))
                self.remove_membership(root, relative, ignored=False)
                fixtures.git(root, "add", "--", relative)
                self.assert_membership_blocked(root)

    def test_required_input_missing_from_index_blocks(self):
        for index, relative in enumerate(REPRESENTATIVE_FILES):
            with self.subTest(relative=relative):
                root = self.new_source("no-index-" + str(index))
                fixtures.git(root, "rm", "--cached", "--", relative)
                self.assert_membership_blocked(root)

    def test_committed_required_symlink_does_not_establish_blob_membership(self):
        for index, relative in enumerate(REPRESENTATIVE_FILES):
            with self.subTest(relative=relative):
                root = self.new_source("symlink-" + str(index))
                path = root / relative
                target = path.with_name("inert-target")
                target.write_bytes(path.read_bytes())
                path.unlink()
                path.symlink_to(target.name)
                fixtures.git(root, "add", ".")
                fixtures.git(root, "commit", "-qm", "record required source symlink")
                self.assert_membership_blocked(root)

    def test_required_gitlink_does_not_establish_blob_membership(self):
        relative = "sw/kernel/Makefile"
        revision = fixtures.git(self.root, "rev-parse", "HEAD")
        fixtures.git(self.root, "update-index", "--cacheinfo", "160000," + revision + "," + relative)
        fixtures.write(self.root / ".gitmodules",
                       '[submodule "inert"]\n\tpath = ' + relative + '\n\turl = ./inert\n')
        fixtures.git(self.root, "add", ".gitmodules")
        fixtures.git(self.root, "commit", "-qm", "record required source gitlink")
        self.assert_membership_blocked(self.root)

    def test_staged_required_blob_changes_remain_dirty(self):
        relative = "sw/kernel/Makefile"
        fixtures.write(self.root / relative, "changed recipe\n")
        fixtures.git(self.root, "add", "--", relative)
        report = inventory.observe_source(self.root)
        self.assertEqual(report["outcome"], "blocked", report)
        self.assertIs(report["dirty"], True)

    def test_raw_worktree_scan_binds_recipe_and_hook_bytes(self):
        for index, relative in enumerate(REPRESENTATIVE_FILES[1:]):
            with self.subTest(relative=relative):
                root = self.new_source("raw-bytes-" + str(index))
                fixtures.write(root / relative, "changed source bytes\n")
                report = inventory.observe_source(root)
                self.assertEqual(report["outcome"], "blocked", report)
                self.assertIs(report["dirty"], True)


if __name__ == "__main__":
    unittest.main()
