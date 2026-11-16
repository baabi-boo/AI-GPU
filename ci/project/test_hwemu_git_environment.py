# SPDX-License-Identifier: Apache-2.0
"""Git scope regressions use owned configs, a real-Git shim and inert markers."""

import os
import shlex
import shutil
import sys
import unittest

import test_hwemu_source as source_tests


class GitEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = source_tests.SourceObservationTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.base = self.fixture.base
        self.root = self.fixture.root
        self.marker = self.base / "filter-was-executed"
        script = self.base / "filter.py"
        script.write_text(
            "from pathlib import Path\nimport sys\n"
            "Path(sys.argv[1]).write_text('unexpected execution\\n')\n"
            "sys.stdout.buffer.write(sys.stdin.buffer.read())\n",
            encoding="utf-8",
        )
        self.command = shlex.join([sys.executable, str(script), str(self.marker)])

    def write_filters(self, config):
        config.parent.mkdir(parents=True, exist_ok=True)
        for kind in ("clean", "process"):
            self.fixture.git(self.root, "config", "--file", str(config),
                             "filter.tripwire." + kind, self.command)

    def assert_clean_identity(self, report):
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(report["revision"], self.fixture.git(self.root, "rev-parse", "HEAD"))
        self.assertEqual(report["tree"], self.fixture.git(self.root, "rev-parse", "HEAD^{tree}"))
        self.assertIs(report["dirty"], False)
        self.assertFalse(self.marker.exists(), "a Git filter was executed")

    def system_environment(self, config):
        real_git = shutil.which("git")
        self.assertIsNotNone(real_git)
        binaries = self.base / "bin"
        binaries.mkdir()
        wrapper = binaries / "git"
        # This substitutes an owned path for Git's compiled system config path.
        # Real Git still decides whether GIT_CONFIG_NOSYSTEM excludes that scope.
        wrapper.write_text(
            "#!" + sys.executable + "\nimport os,sys\n"
            "os.environ.setdefault('GIT_CONFIG_SYSTEM', " + repr(str(config)) + ")\n"
            "os.execv(" + repr(real_git) + ", [" + repr(real_git) + "] + sys.argv[1:])\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        return {"PATH": str(binaries) + os.pathsep + os.environ.get("PATH", ""),
                "GIT_CONFIG_NOSYSTEM": "0", "GIT_CONFIG_GLOBAL": str(config)}

    def test_machine_filters_do_not_block_but_repository_include_still_does(self):
        config = self.base / "owned-system.gitconfig"
        self.write_filters(config)
        environment = self.system_environment(config)
        index = self.root / ".git/index"
        before = (index.read_bytes(), index.stat().st_mtime_ns)
        self.assert_clean_identity(self.fixture.observe(environment=environment))
        self.assertEqual(before, (index.read_bytes(), index.stat().st_mtime_ns))
        self.fixture.git(self.root, "config", "include.path", str(config))
        self.fixture.assert_blocked(self.fixture.observe(environment=environment))
        self.assertFalse(self.marker.exists(), "a repository-included filter was executed")

    def test_default_home_and_xdg_filters_do_not_block_source(self):
        for relative in (".gitconfig", "git/config"):
            with self.subTest(config=relative):
                config = self.fixture.home / relative
                self.write_filters(config)
                try:
                    self.assert_clean_identity(self.fixture.observe())
                finally:
                    config.unlink()

    def configure_scope(self, root, scope, key, value):
        arguments = []
        if scope.startswith("worktree"):
            self.fixture.git(root, "config", "extensions.worktreeConfig", "true")
            arguments.append("--worktree")
        if "include" in scope:
            config = self.base / (root.name + ".gitconfig")
            self.fixture.git(root, "config", "--file", str(config), key, value)
            include_key = ("includeIf.gitdir:" + str(root / ".git") + ".path"
                           if scope == "conditional-include" else "include.path")
            self.fixture.git(root, "config", *arguments, include_key, str(config))
        else:
            self.fixture.git(root, "config", *arguments, key, value)
        self.assertEqual(self.fixture.git(root, "config", "--includes", "--get", key), value)

    def test_repository_worktree_and_included_filters_still_fail_closed(self):
        for scope in ("repository", "repository-include", "conditional-include",
                      "worktree", "worktree-include"):
            for kind in ("clean", "process"):
                with self.subTest(scope=scope, kind=kind):
                    root = self.fixture.new_source(scope + "-" + kind)
                    self.configure_scope(root, scope, "filter.tripwire." + kind, self.command)
                    self.fixture.assert_blocked(self.fixture.observe(root))
                    self.assertFalse(self.marker.exists(), "a configured filter was executed")

    def test_repository_worktree_and_included_partial_clones_still_fail_closed(self):
        for scope in ("repository", "repository-include", "conditional-include",
                      "worktree", "worktree-include"):
            for key, value in (("extensions.partialclone", "origin"),
                               ("remote.origin.promisor", "true")):
                with self.subTest(scope=scope, key=key):
                    root = self.fixture.new_source(scope + "-" + key)
                    self.configure_scope(root, scope, key, value)
                    self.fixture.assert_blocked(self.fixture.observe(root))


if __name__ == "__main__":
    unittest.main()
