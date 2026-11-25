# SPDX-License-Identifier: Apache-2.0
"""Independent controls for linked source metadata and closing file stability."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import governance_replay_source as source


class GovernanceReplaySourceControlsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="governance-source-controls-")
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
        (self.root / "tracked.txt").write_bytes(b"bound source\n")
        self.git("add", "tracked.txt")
        self.git("commit", "-qm", "source fixture")
        self.revision = self.git("rev-parse", "HEAD").decode("ascii").strip()

    def git(self, *arguments, root=None):
        return subprocess.run(
            ["/usr/bin/git", "-c", "core.hooksPath=" + os.devnull,
             "-c", "commit.gpgsign=false", *arguments],
            cwd=self.root if root is None else root, env=self.environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=10,
        ).stdout

    def test_linked_worktree_rejects_common_and_private_grafts(self):
        linked = self.base / "linked"
        self.git("worktree", "add", "--detach", str(linked), self.revision)
        self.assertTrue((linked / ".git").is_file())
        self.assertEqual(source.source_binding(linked, self.revision),
                         source.source_binding(self.root, self.revision))
        directories = self.git(
            "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir",
            root=linked).decode("utf-8").splitlines()
        self.assertEqual(len(set(directories)), 2)
        for directory in directories:
            with self.subTest(directory=Path(directory).name):
                grafts = Path(directory) / "info/grafts"
                grafts.parent.mkdir(exist_ok=True)
                grafts.write_bytes(b"")
                try:
                    with self.assertRaisesRegex(source.SourceBindingError, "grafts"):
                        source.source_binding(linked, self.revision)
                finally:
                    grafts.unlink()

    def test_same_bytes_replaced_after_hashing_fail_closing_stability_check(self):
        expected_binding = source.source_binding(self.root, self.revision)
        tracked = self.root / "tracked.txt"
        original_bytes = tracked.read_bytes()
        original_inode = tracked.stat().st_ino
        replacement = self.base / "replacement"
        replacement.write_bytes(original_bytes)
        metadata = source._metadata
        observations = []

        def replace_after_metadata(*arguments):
            result = metadata(*arguments)
            observations.append(result)
            if len(observations) == 2:
                os.replace(replacement, tracked)
            return result

        with mock.patch.object(source, "_metadata", side_effect=replace_after_metadata):
            with self.assertRaisesRegex(source.SourceBindingError,
                                        "source member changed during observation"):
                source.source_binding(self.root, self.revision)
        self.assertEqual(len(observations), 2)
        self.assertEqual(observations[0], observations[1])
        self.assertEqual(tracked.read_bytes(), original_bytes)
        self.assertNotEqual(tracked.stat().st_ino, original_inode)
        self.assertEqual(source.source_binding(self.root, self.revision), expected_binding)


if __name__ == "__main__":
    unittest.main()
