# SPDX-License-Identifier: Apache-2.0
"""Real CLI shutdown rejects an unwritable stdout without raw diagnostics."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from governance_replay_source import source_binding
from test_governance_replay import packet_fixture


class GovernanceReplayCliControlsTests(unittest.TestCase):
    def test_stdout_flush_failure_has_only_the_static_cli_error(self):
        with tempfile.TemporaryDirectory(prefix="governance-cli-controls-") as temporary:
            base = Path(temporary).resolve()
            source = base / "source"
            tests = source / "ci/project"
            tests.mkdir(parents=True)
            (tests / "test_fixture.py").write_text(
                'import unittest\n'
                'class Case(unittest.TestCase):\n'
                '    def test_first(self):\n'
                '        raise AssertionError("must not execute")\n'
                '    def test_second(self):\n'
                '        raise AssertionError("must not execute")\n', encoding="utf-8")
            environment = {
                "PATH": "/usr/bin:/bin", "HOME": str(base), "LANG": "C", "LC_ALL": "C",
                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
                "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
                "GIT_TERMINAL_PROMPT": "0", "PYTHONDONTWRITEBYTECODE": "1",
            }

            def git(*arguments):
                return subprocess.run(
                    ["/usr/bin/git", "-c", "core.hooksPath=" + os.devnull,
                     "-c", "commit.gpgsign=false", *arguments],
                    cwd=source, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    check=True, timeout=10,
                ).stdout

            git("init", "-q")
            git("config", "core.autocrlf", "false")
            git("config", "core.filemode", "true")
            git("add", "--all", ".")
            git("commit", "-qm", "CLI fixture")
            revision = git("rev-parse", "HEAD").decode().strip()
            binding = source_binding(source, revision)
            members, _, _ = packet_fixture()
            members["logs/source-revision.txt"] = (revision + "\n").encode()
            for name in ("run/started.json", "run/summary.json"):
                record = json.loads(members[name])
                for key in ("source_before", "source_after"):
                    if key in record:
                        record[key].update({field: binding[field] for field in
                            ("head", "tree", "tracked_sha256", "tracked_count", "tracked_bytes")})
                        record[key].update(index_sha256=binding["tracked_sha256"],
                                           worktree_sha256=binding["tracked_sha256"],
                                           gitlinks=[], submodules="")
                members[name] = (json.dumps(record, sort_keys=True, indent=2) + "\n").encode()
            archive = base / "packet.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as packet:
                for name, raw in members.items():
                    packet.writestr(name, raw)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            argv = [sys.executable, "-B", str(Path(__file__).with_name("governance_replay.py").resolve()),
                    "--archive", str(archive), "--expected-revision", revision,
                    "--source-dir", str(source), "--expected-sha256", digest]
            positive = subprocess.run(argv, cwd=base, env=environment, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, timeout=20)
            self.assertEqual((positive.returncode, positive.stderr), (0, b""))
            self.assertTrue(json.loads(positive.stdout)["independent_packet_replay"])
            with open("/dev/full", "wb", buffering=0) as output:
                failed = subprocess.run(argv, cwd=base, env=environment, stdout=output,
                                        stderr=subprocess.PIPE, timeout=20)
            self.assertEqual((failed.returncode, failed.stderr), (1, b"governance replay failed\n"))


if __name__ == "__main__":
    unittest.main()
