# SPDX-License-Identifier: Apache-2.0
"""Small real Git checkouts exercise governance source binding."""

import json
import os
from pathlib import Path
import py_compile
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

import governance_run as runner


class GovernanceSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="governance-source-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.source = self.base / "source"
        self.source.mkdir()
        self.git_executable = shutil.which("git")
        self.assertIsNotNone(self.git_executable, "governance source binding requires Git")
        self.environment = {
            key: value for key, value in os.environ.items() if not key.startswith("GIT_")
        }
        self.environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                                GIT_TERMINAL_PROMPT="0", PYTHONDONTWRITEBYTECODE="1")
        self.git("init", "-q")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "core.filemode", "true")
        self.git("config", "core.symlinks", "true")
        self.tracked = self.write("tracked.txt", "original source\n")
        self.write("nested/input.txt", "nested source\n")
        self.commit()

    def git(self, *arguments):
        return subprocess.run(
            [self.git_executable, "-c", "core.hooksPath=" + os.devnull, *arguments],
            cwd=self.source, env=self.environment, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=10, check=True,
        ).stdout.rstrip("\n")

    def write(self, relative, content):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def commit(self):
        self.git("add", "--all", ".")
        self.git("-c", "user.name=Governance fixture", "-c",
                 "user.email=governance-fixture@example.invalid", "-c",
                 "commit.gpgsign=false", "commit", "-qm", "tiny source fixture")

    def snapshot(self):
        with mock.patch.object(runner, "ROOT", self.source):
            return runner.source_snapshot()

    def assert_git_clean(self):
        self.assertEqual(self.git("status", "--porcelain=v1", "--untracked-files=all"), "")

    def prepare_cli(self, source=None):
        script = self.source / "ci/project/governance_run.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(runner.__file__).resolve(), script)
        self.write("ci/project/test_probe.py", textwrap.dedent(source or """
            from pathlib import Path
            import unittest

            class Probe(unittest.TestCase):
                def test_committed_source(self):
                    self.assertEqual(Path('tracked.txt').read_text(), 'original source\\n')
        """))
        self.commit()
        return script

    def run_cli(self, script):
        output = self.base / "run"
        completed = subprocess.run(
            [sys.executable, str(script), "--output-dir", str(output)],
            cwd=self.base, env=self.environment, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=20, check=False)
        summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        return completed, summary, output

    def test_complete_tiny_checkout_is_clean_and_stable(self):
        executable = self.write("run.sh", "#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
        (self.source / "link").symlink_to("tracked.txt")
        self.commit()
        snapshot = self.snapshot()
        self.assertTrue(snapshot["clean"])
        self.assertEqual(snapshot["head"], self.git("rev-parse", "HEAD"))
        self.assertEqual(snapshot["tree"], self.git("rev-parse", "HEAD^{tree}"))
        self.assertEqual(snapshot["status_porcelain"], "")
        self.assertEqual(snapshot["tracked_count"], 4)
        self.assertEqual(snapshot["mismatch_count"], 0)
        self.assertEqual(snapshot, self.snapshot())

    def test_complete_tiny_cli_population_qualifies(self):
        script = self.prepare_cli()
        completed, summary, output = self.run_cli(script)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertTrue(summary["governance_passed"])
        self.assertTrue(summary["source_stable"])
        self.assertEqual(summary["execution"]["outcome_counts"], {"success": 1})
        discovered = json.loads((output / "discovered.json").read_text(encoding="utf-8"))
        self.assertEqual(discovered["test_ids"], ["test_probe.Probe.test_committed_source"])
        self.assert_git_clean()

    def test_ordinary_worktree_edit_is_recorded_as_dirty(self):
        before = self.snapshot()
        self.tracked.write_text("modified source\n", encoding="utf-8")
        after = self.snapshot()
        self.assertFalse(after["clean"])
        self.assertEqual(after["head"], before["head"])
        self.assertEqual(after["tracked_sha256"], before["tracked_sha256"])
        self.assertNotEqual(after["worktree_sha256"], before["worktree_sha256"])
        self.assertGreater(after["mismatch_count"], 0)

    def test_staged_source_edit_is_recorded_as_dirty(self):
        self.tracked.write_text("staged source\n", encoding="utf-8")
        self.git("add", "tracked.txt")
        snapshot = self.snapshot()
        self.assertFalse(snapshot["clean"])
        self.assertGreater(snapshot["mismatch_count"], 0)

    def test_deleted_tracked_file_is_recorded_as_dirty(self):
        self.tracked.unlink()
        snapshot = self.snapshot()
        self.assertFalse(snapshot["clean"])
        self.assertGreater(snapshot["mismatch_count"], 0)

    def test_assume_unchanged_rejects_even_unmodified_bytes(self):
        self.git("update-index", "--assume-unchanged", "tracked.txt")
        self.assert_git_clean()
        with self.assertRaises(ValueError):
            self.snapshot()

    def test_assume_unchanged_cannot_hide_modified_test_source(self):
        self.write("ci/project/test_hidden.py", "import unittest\n")
        self.commit()
        self.git("update-index", "--assume-unchanged", "ci/project/test_hidden.py")
        self.write("ci/project/test_hidden.py", "raise RuntimeError('uncommitted code')\n")
        self.assert_git_clean()
        with self.assertRaises(ValueError):
            self.snapshot()

    def test_skip_worktree_rejects_even_materialized_unchanged_bytes(self):
        self.git("update-index", "--skip-worktree", "tracked.txt")
        self.assert_git_clean()
        with self.assertRaises(ValueError):
            self.snapshot()

    def test_skip_worktree_cannot_hide_a_missing_file(self):
        self.git("update-index", "--skip-worktree", "tracked.txt")
        self.tracked.unlink()
        self.assert_git_clean()
        with self.assertRaises(ValueError):
            self.snapshot()

    def test_sparse_checkout_cannot_qualify_an_omitted_test_population(self):
        self.write("ci/project/test_visible.py", "import unittest\n")
        omitted = self.write("ci/project/test_omitted.py", "import unittest\n")
        self.commit()
        self.git("sparse-checkout", "set", "--no-cone", "/ci/project/test_visible.py")
        self.assertFalse(omitted.exists())
        self.assertTrue((self.source / "ci/project/test_visible.py").is_file())
        self.assert_git_clean()
        with self.assertRaises(ValueError):
            self.snapshot()

    def test_clean_filter_cannot_hide_different_raw_source_bytes(self):
        marker = self.base / "filter-executed"
        command = ("from pathlib import Path; import sys; Path(" + repr(str(marker))
                   + ").write_text('executed'); "
                   "sys.stdout.buffer.write(sys.stdin.buffer.read().replace(b'filtered', b'original'))")
        self.git("config", "filter.canonical.clean", shlex.join([sys.executable, "-c", command]))
        self.write(".gitattributes", "tracked.txt filter=canonical\n")
        self.commit()
        self.tracked.write_text("filtered source\n", encoding="utf-8")
        self.assert_git_clean()
        self.assertTrue(marker.exists())
        marker.unlink()
        self.assertNotEqual(self.git("hash-object", "--no-filters", "tracked.txt"),
                            self.git("rev-parse", "HEAD:tracked.txt"))
        with self.assertRaises(ValueError):
            self.snapshot()
        self.assertFalse(marker.exists(), "source binding executed a Git clean filter")

    def test_core_filemode_false_cannot_hide_executable_bit_change(self):
        self.git("config", "core.filemode", "false")
        self.tracked.chmod(0o755)
        self.assert_git_clean()
        snapshot = self.snapshot()
        self.assertFalse(snapshot["clean"])
        self.assertGreater(snapshot["mismatch_count"], 0)

    def test_autocrlf_clean_status_cannot_hide_different_raw_bytes(self):
        before = self.snapshot()
        self.git("config", "core.autocrlf", "true")
        self.tracked.write_bytes(self.tracked.read_bytes().replace(b"\n", b"\r\n"))
        self.git("add", "tracked.txt")
        self.assert_git_clean()
        after = self.snapshot()
        self.assertFalse(after["clean"])
        self.assertNotEqual(after["worktree_sha256"], before["worktree_sha256"])
        self.assertGreater(after["mismatch_count"], 0)

    def test_symlink_target_change_is_recorded_as_dirty(self):
        link = self.source / "link"
        link.symlink_to("tracked.txt")
        self.commit()
        link.unlink()
        link.symlink_to("nested/input.txt")
        snapshot = self.snapshot()
        self.assertFalse(snapshot["clean"])
        self.assertGreater(snapshot["mismatch_count"], 0)

    def test_symlink_replaced_by_regular_file_cannot_hide_behind_git_config(self):
        link = self.source / "link"
        link.symlink_to("tracked.txt")
        self.commit()
        self.git("config", "core.symlinks", "false")
        link.unlink()
        link.write_text("tracked.txt", encoding="utf-8")
        self.assert_git_clean()
        snapshot = self.snapshot()
        self.assertFalse(snapshot["clean"])
        self.assertGreater(snapshot["mismatch_count"], 0)

    def test_parent_symlink_is_rejected_even_when_it_points_to_original_bytes(self):
        nested = self.source / "nested"
        outside = self.base / "relocated"
        nested.rename(outside)
        nested.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.snapshot()

    def test_directory_in_place_of_tracked_regular_file_is_rejected(self):
        self.tracked.unlink()
        self.tracked.mkdir()
        with self.assertRaises(ValueError):
            self.snapshot()

    def test_file_replacement_during_raw_read_is_rejected(self):
        original = self.tracked.stat()
        replacement = self.base / "replacement"
        replacement.write_bytes(self.tracked.read_bytes())
        real_read = os.read
        replaced = False

        def replace_during_read(descriptor, size):
            nonlocal replaced
            observed = os.fstat(descriptor)
            content = real_read(descriptor, size)
            if not replaced and (observed.st_dev, observed.st_ino) == (original.st_dev, original.st_ino):
                os.replace(replacement, self.tracked)
                replaced = True
            return content

        with mock.patch.object(runner.os, "read", side_effect=replace_during_read):
            with self.assertRaises(ValueError):
                self.snapshot()
        self.assertTrue(replaced, "the fixture did not reach the tracked-file read")
        self.assert_git_clean()

    def test_uninitialized_gitlink_remains_a_pinned_allowed_entry(self):
        pin = self.git("rev-parse", "HEAD")
        self.write(".gitmodules", '[submodule "fixture"]\n\tpath = vendor/fixture\n'
                   '\turl = https://example.invalid/governance-fixture.git\n')
        self.git("add", ".gitmodules")
        self.git("update-index", "--add", "--cacheinfo", "160000," + pin + ",vendor/fixture")
        (self.source / "vendor/fixture").mkdir(parents=True)
        self.git("-c", "user.name=Governance fixture", "-c",
                 "user.email=governance-fixture@example.invalid", "-c",
                 "commit.gpgsign=false", "commit", "-qm", "record uninitialized gitlink")
        self.assertEqual(list((self.source / "vendor/fixture").iterdir()), [])
        self.assert_git_clean()
        snapshot = self.snapshot()
        self.assertTrue(snapshot["clean"])
        self.assertIn("-" + pin + " vendor/fixture", snapshot["submodules"])
        self.assertEqual(len(snapshot["gitlinks"]), 1)
        self.assertIn(pin, json.dumps(snapshot["gitlinks"]))
        self.assertIn("vendor/fixture", json.dumps(snapshot["gitlinks"]))

    def test_git_replacements_do_not_redefine_the_bound_head_tree(self):
        original = self.git("rev-parse", "HEAD")
        original_tree = self.git("rev-parse", "HEAD^{tree}")
        self.tracked.write_text("replacement source\n", encoding="utf-8")
        self.commit()
        replacement = self.git("rev-parse", "HEAD")
        self.git("reset", "--hard", original)
        self.git("replace", original, replacement)
        self.assertNotEqual(self.git("rev-parse", "HEAD^{tree}"), original_tree)
        snapshot = self.snapshot()
        self.assertTrue(snapshot["clean"])
        self.assertEqual(snapshot["head"], original)
        self.assertEqual(snapshot["tree"], original_tree)

    def test_ignored_imported_python_source_cannot_qualify(self):
        self.write(".gitignore", "ci/project/ignored_helper.py\n")
        script = self.prepare_cli("""
            import ignored_helper
            import unittest

            class Probe(unittest.TestCase):
                def test_ignored_helper(self):
                    self.assertEqual(ignored_helper.value, 17)
        """)
        self.write("ci/project/ignored_helper.py", "value = 17\n")
        self.assert_git_clean()
        completed, summary, _ = self.run_cli(script)
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertFalse(summary["governance_passed"])
        self.assertTrue(summary["errors"])

    def test_ignored_timestamp_valid_bytecode_cannot_replace_committed_test_code(self):
        self.write(".gitignore", "__pycache__/\n")
        script = self.prepare_cli("""
            import unittest

            class Probe(unittest.TestCase):
                def test_committed_failure(self):
                    self.assertEqual(17, 18)
        """)
        test_source = self.source / "ci/project/test_probe.py"
        original = test_source.read_bytes()
        original_stat = test_source.stat()
        altered = original.replace(b"17, 18", b"17, 17")
        self.assertNotEqual(original, altered)
        self.assertEqual(len(original), len(altered))
        test_source.write_bytes(altered)
        os.utime(test_source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        cached = Path(py_compile.compile(str(test_source), doraise=True))
        test_source.write_bytes(original)
        os.utime(test_source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        self.assertTrue(cached.is_file())
        self.assert_git_clean()
        completed, summary, _ = self.run_cli(script)
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertFalse(summary["governance_passed"])
        self.assertTrue(summary["errors"])
        self.assertRegex(" ".join(error["message"] for error in summary["errors"]), "bytecode|cached")
        self.assertEqual(test_source.read_bytes(), original)

    def test_self_deleting_cached_bytecode_is_rejected_before_import(self):
        self._assert_self_deleting_cache_rejected(symlink_cache=False)

    def test_self_deleting_bytecode_in_ignored_symlink_cache_is_rejected_before_import(self):
        self._assert_self_deleting_cache_rejected(symlink_cache=True)

    def _assert_self_deleting_cache_rejected(self, *, symlink_cache):
        # The pattern must ignore both a directory and a symlink at this name.
        self.write(".gitignore", "__pycache__\n")
        deletion = "from pathlib import Path; Path(__cached__).unlink()"
        placeholder = "#" + " " * (len(deletion) - 1)
        script = self.prepare_cli(placeholder + "\n" + textwrap.dedent("""
            import unittest

            class Probe(unittest.TestCase):
                def test_committed_failure(self):
                    self.assertEqual(17, 18)
        """))
        test_source = self.source / "ci/project/test_probe.py"
        original = test_source.read_bytes()
        original_stat = test_source.stat()
        altered = original.replace(placeholder.encode(), deletion.encode()).replace(b"17, 18", b"17, 17")
        self.assertNotEqual(original, altered)
        self.assertEqual(len(original), len(altered))
        test_source.write_bytes(altered)
        os.utime(test_source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        cached = Path(py_compile.compile(str(test_source), doraise=True))
        test_source.write_bytes(original)
        os.utime(test_source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        if symlink_cache:
            cache_directory = cached.parent
            relocated = self.base / "bytecode-cache"
            cache_directory.rename(relocated)
            cache_directory.symlink_to(relocated, target_is_directory=True)
            self.assertNotIn(cached.name, self.git(
                "ls-files", "--others", "--ignored", "--exclude-standard"))
        self.assert_git_clean()
        self.assertTrue(cached.is_file())
        completed, summary, _ = self.run_cli(script)
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertFalse(summary["governance_passed"])
        self.assertFalse(summary["execution_completed"])
        self.assertTrue(summary["errors"])
        self.assertTrue(cached.is_file(), "unbound cached code reached import execution")
        self.assertEqual(test_source.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
