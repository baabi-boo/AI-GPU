# SPDX-License-Identifier: Apache-2.0
"""Real small checkouts exercise independent governance replay source binding."""

import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest import mock

import governance_replay_source as source


class GovernanceReplaySourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="governance-replay-source-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / "source"
        self.root.mkdir()
        self.environment = {
            "PATH": "/usr/bin:/bin", "HOME": str(self.base), "LANG": "C", "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            "GIT_TERMINAL_PROMPT": "0", "PYTHONDONTWRITEBYTECODE": "1",
        }
        self.git("init", "-q")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "core.filemode", "true")
        self.git("config", "core.symlinks", "true")
        self.write("tracked.txt", b"original source\n")
        self.write("nested/input.txt", b"nested source\n")
        self.commit()

    def git(self, *arguments, root=None):
        return subprocess.run(
            ["/usr/bin/git", "-c", "core.hooksPath=" + os.devnull,
             "-c", "commit.gpgsign=false", *arguments],
            cwd=self.root if root is None else root, env=self.environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=10,
        ).stdout

    def write(self, name, contents):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return path

    def commit(self):
        self.git("add", "--all", ".")
        self.git("commit", "-qm", "source fixture")
        self.revision = self.git("rev-parse", "HEAD").decode().strip()

    def bind(self):
        return source.source_binding(self.root, self.revision)

    def test_exact_checkout_matches_digest_grammar_without_loading_source(self):
        marker = self.base / "executed"
        self.write("ci/project/test_poison.py",
                   ("from pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\n").encode())
        executable = self.write("run.sh", b"#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
        (self.root / "link").symlink_to("tracked.txt")
        self.commit()
        identities = {}
        total_bytes = 0
        for record in self.git("ls-tree", "-r", "-z", "HEAD").split(b"\0")[:-1]:
            header, name = record.split(b"\t")
            mode, _kind, oid = header.split(b" ")
            identities[name] = mode + b" " + oid + b"\t" + name + b"\0"
            total_bytes += (self.root / name.decode()).lstat().st_size
        expected = hashlib.sha256(b"".join(identities[name] for name in sorted(identities))).hexdigest()
        binding = self.bind()
        self.assertEqual(binding, self.bind())
        self.assertEqual(binding["head"], self.revision)
        self.assertEqual(binding["tree"], self.git("rev-parse", "HEAD^{tree}").decode().strip())
        self.assertEqual(binding["tracked_sha256"], expected)
        self.assertEqual(binding["tracked_count"], len(identities))
        self.assertEqual(binding["tracked_bytes"], total_bytes)
        self.assertEqual(binding["object_format"], "sha1")
        self.assertEqual(binding["gitlinks"], [])
        self.assertNotIn("root", binding)
        self.assertNotIn("git", binding)
        self.assertFalse(marker.exists(), "selected checkout code was executed")

    def test_revision_requires_exact_full_lowercase_commit(self):
        for revision in ("HEAD", "--help", self.revision[:12], self.revision.upper(), "0" * 40):
            with self.subTest(revision=revision), self.assertRaises(source.SourceBindingError):
                source.source_binding(self.root, revision)

    def test_materialized_edit_and_deletion_are_rejected(self):
        self.write("tracked.txt", b"different source\n")
        with self.assertRaisesRegex(source.SourceBindingError, "materialized"):
            self.bind()
        (self.root / "tracked.txt").unlink()
        with self.assertRaises(source.SourceBindingError):
            self.bind()

    def test_staged_edit_is_rejected(self):
        self.write("tracked.txt", b"staged edit\n")
        self.git("add", "tracked.txt")
        with self.assertRaisesRegex(source.SourceBindingError, "index differs"):
            self.bind()

    def test_untracked_file_is_rejected(self):
        self.write("untracked.txt", b"extra source\n")
        with self.assertRaisesRegex(source.SourceBindingError, "untracked"):
            self.bind()

    def test_assume_unchanged_and_skip_worktree_are_rejected(self):
        for flag in ("assume-unchanged", "skip-worktree"):
            with self.subTest(flag=flag):
                self.git("update-index", "--" + flag, "tracked.txt")
                with self.assertRaisesRegex(source.SourceBindingError, "hidden, sparse"):
                    self.bind()
                self.git("update-index", "--no-" + flag, "tracked.txt")

    def test_raw_mode_changes_cannot_hide_behind_filemode_config(self):
        self.git("config", "core.filemode", "false")
        (self.root / "tracked.txt").chmod(0o755)
        self.assertEqual(self.git("status", "--porcelain"), b"")
        with self.assertRaisesRegex(source.SourceBindingError, "materialized"):
            self.bind()

    def test_raw_line_endings_cannot_hide_behind_attributes(self):
        self.write(".gitattributes", b"tracked.txt text\n")
        self.commit()
        self.write("tracked.txt", b"original source\r\n")
        with self.assertRaisesRegex(source.SourceBindingError, "materialized"):
            self.bind()

    def test_tracked_symlink_cannot_be_replaced_by_regular_file(self):
        (self.root / "link").symlink_to("tracked.txt")
        self.commit()
        self.git("config", "core.symlinks", "false")
        (self.root / "link").unlink()
        self.write("link", b"tracked.txt")
        with self.assertRaisesRegex(source.SourceBindingError, "materialized"):
            self.bind()

    def test_symlink_root_and_parent_traversal_are_rejected(self):
        alias = self.base / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(source.SourceBindingError):
            source.source_binding(alias, self.revision)
        external = self.base / "external"
        (self.root / "nested").rename(external)
        (self.root / "nested").symlink_to(external, target_is_directory=True)
        with self.assertRaises(source.SourceBindingError):
            self.bind()

    def test_nonregular_tracked_member_fails_without_blocking(self):
        (self.root / "tracked.txt").unlink()
        os.mkfifo(self.root / "tracked.txt")
        start = time.monotonic()
        with self.assertRaises(source.SourceBindingError):
            self.bind()
        self.assertLess(time.monotonic() - start, 5)

    def test_unsafe_filters_and_deferred_fetch_configuration_are_rejected_inertly(self):
        marker = self.base / "filter-executed"
        for key in ("filter.fixture.clean", "filter.fixture.smudge", "filter.fixture.process",
                    "diff.fixture.textconv", "remote.origin.promisor",
                    "remote.origin.partialclonefilter", "extensions.partialclone"):
            with self.subTest(key=key):
                self.git("config", key, "touch " + str(marker))
                with self.assertRaisesRegex(source.SourceBindingError, "executable filters|deferred"):
                    self.bind()
                self.assertFalse(marker.exists())
                self.git("config", "--unset", key)

    def test_included_executable_configuration_is_rejected(self):
        included = self.base / "included-config"
        included.write_text("[filter \"fixture\"]\nclean = false\n", encoding="utf-8")
        self.git("config", "include.path", str(included))
        with self.assertRaisesRegex(source.SourceBindingError, "executable filters"):
            self.bind()

    def test_sparse_checkout_configuration_is_rejected(self):
        self.git("config", "core.sparseCheckout", "true")
        with self.assertRaisesRegex(source.SourceBindingError, "sparse"):
            self.bind()

    def test_replacement_refs_are_rejected_even_with_materialized_original(self):
        original = self.revision
        self.write("tracked.txt", b"replacement\n")
        self.commit()
        replacement = self.revision
        self.git("reset", "--hard", original)
        self.revision = original
        self.git("replace", original, replacement)
        self.git("pack-refs", "--all")
        with self.assertRaisesRegex(source.SourceBindingError, "replacement refs"):
            self.bind()

    def test_grafts_are_rejected_even_when_empty(self):
        (self.root / ".git/info/grafts").write_bytes(b"")
        with self.assertRaisesRegex(source.SourceBindingError, "grafts"):
            self.bind()

    def test_ignored_python_and_bytecode_are_rejected_but_inert_data_is_allowed(self):
        self.write(".gitignore", b"ignored/\n")
        self.commit()
        self.write("ignored/data.txt", b"inert data\n")
        self.bind()
        for name in ("helper.py", "helper.pyc", "helper.pyo", "helper.so"):
            with self.subTest(name=name):
                path = self.write("ignored/" + name, b"unbound code\n")
                with self.assertRaisesRegex(source.SourceBindingError, "ignored Python"):
                    self.bind()
                path.unlink()

    def test_bytecode_behind_ignored_symlink_cache_is_rejected_before_loading(self):
        self.write(".gitignore", b"__pycache__/\n")
        self.write("ci/project/test_probe.py", b"raise RuntimeError('must not load')\n")
        self.commit()
        cache = self.base / "cache"
        cache.mkdir()
        (self.root / "ci/project/__pycache__").symlink_to(cache, target_is_directory=True)
        cached = Path(importlib.util.cache_from_source(str(self.root / "ci/project/test_probe.py")))
        cached.write_bytes(b"unbound cache")
        with self.assertRaises(source.SourceBindingError):
            self.bind()
        self.assertEqual(cached.read_bytes(), b"unbound cache")

    def test_tracked_python_symlink_and_bytecode_are_rejected(self):
        (self.root / "helper.py").symlink_to("tracked.txt")
        self.commit()
        with self.assertRaisesRegex(source.SourceBindingError, "Python bytecode or symlink"):
            self.bind()
        (self.root / "helper.py").unlink()
        self.write("helper.pyc", b"tracked cache")
        self.commit()
        with self.assertRaisesRegex(source.SourceBindingError, "Python bytecode or symlink"):
            self.bind()

    def test_gitlink_projection_ignores_initialization_state(self):
        pin = self.revision
        self.write(".gitmodules", b'[submodule "fixture"]\npath = vendor/fixture\n'
                   b'url = https://example.invalid/fixture.git\n')
        self.git("add", ".gitmodules")
        self.git("update-index", "--add", "--cacheinfo", "160000," + pin + ",vendor/fixture")
        self.git("commit", "-qm", "gitlink fixture")
        self.revision = self.git("rev-parse", "HEAD").decode().strip()
        before = self.bind()
        self.git("clone", "-q", "--no-hardlinks", str(self.root), str(self.root / "vendor/fixture"))
        self.git("checkout", "-q", pin, root=self.root / "vendor/fixture")
        self.assertEqual(self.bind(), before)
        self.assertEqual(before["gitlinks"], [{"path": "vendor/fixture", "oid": pin}])

    def test_ambient_git_and_path_overrides_do_not_choose_checkout_or_tool(self):
        marker = self.base / "fake-git-ran"
        fake_bin = self.base / "bin"
        fake_bin.mkdir()
        fake = fake_bin / "git"
        fake.write_text("#!/bin/sh\ntouch " + str(marker) + "\nexit 97\n", encoding="utf-8")
        fake.chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": str(fake_bin), "GIT_DIR": str(self.base),
                                          "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.bare",
                                          "GIT_CONFIG_VALUE_0": "true"}):
            self.assertEqual(self.bind()["head"], self.revision)
        self.assertFalse(marker.exists())

    def test_file_replacement_during_raw_read_is_rejected(self):
        tracked = self.root / "tracked.txt"
        expected = tracked.stat()
        replacement = self.base / "replacement"
        replacement.write_bytes(tracked.read_bytes())
        read = os.read
        replaced = False

        def replace_during_read(descriptor, size):
            nonlocal replaced
            contents = read(descriptor, size)
            observed = os.fstat(descriptor)
            if not replaced and (observed.st_dev, observed.st_ino) == (expected.st_dev, expected.st_ino):
                os.replace(replacement, tracked)
                replaced = True
            return contents

        with mock.patch.object(source.os, "read", side_effect=replace_during_read):
            with self.assertRaisesRegex(source.SourceBindingError, "changed"):
                self.bind()
        self.assertTrue(replaced)

    def test_new_untracked_file_during_observation_is_rejected(self):
        read_member = source._read_member
        changed = False

        def add_untracked(*arguments):
            nonlocal changed
            result = read_member(*arguments)
            if not changed:
                self.write("appeared.txt", b"late input\n")
                changed = True
            return result

        with mock.patch.object(source, "_read_member", side_effect=add_untracked):
            with self.assertRaisesRegex(source.SourceBindingError, "untracked"):
                self.bind()

    def test_source_inventory_and_materialized_bytes_are_bounded(self):
        for limit in ("MAX_SOURCE_FILES", "MAX_SOURCE_FILE_BYTES", "MAX_SOURCE_BYTES"):
            with self.subTest(limit=limit), mock.patch.object(source, limit, 1):
                with self.assertRaisesRegex(source.SourceBindingError, "limit"):
                    self.bind()

    def test_unsafe_git_path_is_rejected(self):
        self.write("control\nname.txt", b"unsafe filename\n")
        self.commit()
        with self.assertRaisesRegex(source.SourceBindingError, "unsafe Git source filename"):
            self.bind()

    def test_git_child_output_and_time_are_bounded(self):
        fake_git = self.base / "fake-git"
        fake_git.write_text("#!/usr/bin/python3\nimport os\nos.write(1, b'x' * 10000)\n",
                            encoding="utf-8")
        fake_git.chmod(0o755)
        with mock.patch.object(source, "GIT_EXECUTABLE", str(fake_git)), \
                mock.patch.object(source, "MAX_GIT_BYTES", 100):
            with self.assertRaisesRegex(source.SourceBindingError, "byte limit"):
                source._git(self.root, [], time.monotonic() + 5)
        fake_git.write_text("#!/usr/bin/python3\nimport time\ntime.sleep(20)\n", encoding="utf-8")
        start = time.monotonic()
        with mock.patch.object(source, "GIT_EXECUTABLE", str(fake_git)):
            with self.assertRaisesRegex(source.SourceBindingError, "timed out"):
                source._git(self.root, [], time.monotonic() + 0.1)
        self.assertLess(time.monotonic() - start, 3)


if __name__ == "__main__":
    unittest.main()
