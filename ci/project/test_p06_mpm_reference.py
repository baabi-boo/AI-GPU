# SPDX-License-Identifier: Apache-2.0
"""Exercise reference staging with real shallow Git repositories, without GPU tools."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import baseline_inventory
import p06_mpm_execute as native
import p06_mpm_parent as parent
import p06_mpm_synthesis as synthesis


@unittest.skipUnless(shutil.which("git"), "Git is required for reference staging")
class ShallowReferenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mpm-shallow-reference-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.environment = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull,
                                GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0",
                                GIT_AUTHOR_NAME="Reference fixture",
                                GIT_AUTHOR_EMAIL="fixture@example.invalid",
                                GIT_COMMITTER_NAME="Reference fixture",
                                GIT_COMMITTER_EMAIL="fixture@example.invalid")
        origin = self.root / "origin"
        origin.mkdir()
        self.git(origin, "init", "-q", "--initial-branch=original")
        inputs = set(native.CRITICAL) | set(synthesis.INPUTS) | set(baseline_inventory.SOURCE_INPUTS)
        for name in inputs:
            path = origin / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture input: " + name + "\n")
        (origin / "VERSION").write_bytes((native.ROOT / "VERSION").read_bytes())
        (origin / ".gitmodules").write_text("")
        (origin / "payload").write_text("original production\n")
        self.git(origin, "add", ".")
        self.git(origin, "commit", "-qm", "reference")
        self.pin = self.git(origin, "rev-parse", "HEAD").stdout.strip()
        self.git(origin, "checkout", "-q", "--orphan", "candidate")
        (origin / "payload").write_text("candidate production\n")
        self.git(origin, "add", ".")
        self.git(origin, "commit", "-qm", "candidate")
        self.source = self.root / "source"
        self.git(self.root, "clone", "-q", "--depth=1", "--branch=candidate",
                 origin.as_uri(), str(self.source))
        self.git(self.source, "fetch", "--no-tags", "--depth=1", "origin", self.pin)
        self.assertEqual(self.git(self.source, "rev-parse", "--is-shallow-repository").stdout.strip(), "true")
        self.assertNotIn(self.pin, self.git(self.source, "rev-list", "--all").stdout.splitlines())
        self.git(self.source, "cat-file", "-e", self.pin + "^{tree}")
        self.before = native.source_snapshot(self.source)
        native.check_source(self.before, False)
        self.synthesis_before = synthesis.source_identity(self.source)

    def run_command(self, argv, cwd, check=True):
        return subprocess.run(argv, cwd=cwd, env=self.environment, check=check,
                              capture_output=True, text=True, timeout=20)

    def git(self, cwd, *arguments, check=True):
        return self.run_command(["git", *arguments], cwd, check)

    def assert_candidate_unchanged(self):
        self.assertEqual(native.source_snapshot(self.source), self.before)
        self.assertEqual(synthesis.source_identity(self.source), self.synthesis_before)
        self.assertEqual((self.source / "payload").read_text(), "candidate production\n")

    def variants(self):
        return ((parent, "PARENT", "native"), (synthesis, "REFERENCE", "synthesis"))

    def test_both_runners_stage_fetched_reference_outside_shallow_history(self):
        for module, constant, label in self.variants():
            with self.subTest(runner=label), mock.patch.object(module, constant, self.pin):
                reference = self.root / (label + "-reference")
                self.run_command(module.reference_checkout_argv(self.source, reference), self.root)
                self.assertEqual(self.git(reference, "rev-parse", "HEAD").stdout.strip(), self.pin)
                self.assertEqual(self.git(reference, "rev-parse", "HEAD^{tree}").stdout,
                                 self.git(self.source, "rev-parse", self.pin + "^{tree}").stdout)
                self.assertEqual((reference / "payload").read_text(), "original production\n")
                self.assertEqual(self.git(reference, "status", "--porcelain").stdout, "")
                self.assert_candidate_unchanged()
                (reference / "payload").write_text("reference-only edit\n")
                (reference / "new-harness").write_text("reference-only overlay\n")
                self.assert_candidate_unchanged()

    def test_unknown_reference_fails_without_changing_candidate(self):
        for module, constant, label in self.variants():
            with self.subTest(runner=label), mock.patch.object(module, constant, "0" * 40):
                reference = self.root / (label + "-missing")
                result = self.run_command(module.reference_checkout_argv(self.source, reference),
                                          self.root, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((reference / "payload").exists())
                self.assert_candidate_unchanged()

    def test_existing_reference_directory_is_not_overwritten(self):
        for module, constant, label in self.variants():
            with self.subTest(runner=label), mock.patch.object(module, constant, self.pin):
                reference = self.root / (label + "-existing")
                reference.mkdir()
                marker = reference / "keep"
                marker.write_text("preexisting data\n")
                result = self.run_command(module.reference_checkout_argv(self.source, reference),
                                          self.root, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(marker.read_text(), "preexisting data\n")
                self.assert_candidate_unchanged()


if __name__ == "__main__":
    unittest.main()
