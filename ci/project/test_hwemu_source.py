# SPDX-License-Identifier: Apache-2.0
"""Source observation regressions use isolated Git repositories and inert markers."""

import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

from hwemu_source import REQUIRED_SOURCE_INPUTS


PROJECT = Path(__file__).resolve().parent
SOURCE_FILES = {
    "VERSION": "VORTEX_VERSION=3.0\nTOOLCHAIN_REV=v3.0.2\n"
               "GEM5_REV=v25.0.0.1\n"
               "FIRESIM_REV=57bb93f1e23daf46198659ddd93608f70121fee0\n",
    ".gitmodules": "",
    ".gitignore": "/build*/\n",
    ".gitattributes": "payload.dat filter=tripwire\n",
    "configure": "source fixture\n",
    "config.mk.in": "source fixture\n",
    "VX_config.toml": "source fixture\n",
    "VX_types.toml": "source fixture\n",
    "ci/gen_config.py": "source fixture\n",
    "ci/blackbox.sh": "source fixture\n",
    "payload.dat": "original payload\n",
}
OBSERVER = (
    "import json,sys; from pathlib import Path; "
    "sys.path.insert(0,sys.argv[1]); import hwemu_inventory; "
    "print(json.dumps(hwemu_inventory.observe_source(Path(sys.argv[2]))))"
)


class SourceObservationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.filter_count = 0
        self.root = self.new_source("source")

    def environment(self):
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith("GIT_")}
        environment.update(HOME=str(self.home), XDG_CONFIG_HOME=str(self.home),
                           GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                           LC_ALL="C")
        return environment

    def git(self, root, *arguments):
        return subprocess.run(
            ["git", "-C", str(root), "-c", "user.name=Source Fixture",
             "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
             "-c", "protocol.allow=never", "-c", "protocol.file.allow=always",
             *arguments], env=self.environment(), check=True, capture_output=True,
            text=True, timeout=10,
        ).stdout.strip()

    def new_source(self, name):
        root = self.base / name
        root.mkdir()
        for relative, content in SOURCE_FILES.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        for relative in REQUIRED_SOURCE_INPUTS:
            path = root / relative
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("inert source fixture\n", encoding="utf-8")
        self.git(root, "init", "-q", "--template=")
        self.git(root, "add", ".")
        self.git(root, "commit", "-qm", "inert source fixture")
        return root

    def kill_observer(self, process):
        # Git probes can create their own sessions, so clean up descendants too.
        def kill_descendants(pid):
            try:
                children = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
            except OSError:
                children = []
            for child in children:
                kill_descendants(int(child))
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        kill_descendants(process.pid)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def observe(self, root=None, environment=None):
        root = self.root if root is None else root
        variables = self.environment()
        variables.update(environment or {})
        process = subprocess.Popen(
            [sys.executable, "-I", "-c", OBSERVER, str(PROJECT), str(root)],
            env=variables, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            self.kill_observer(process)
            process.communicate(timeout=5)
            self.fail("source observation exceeded the five-second hard timeout")
        self.assertEqual(process.returncode, 0, stderr)
        report = json.loads(stdout)
        self.assertNotIn(str(self.base), json.dumps(report))
        return report

    def assert_blocked(self, report):
        self.assertEqual(report["outcome"], "blocked", report)
        self.assertTrue(report["blockers"], report)

    def install_filter(self, root, kind):
        marker = self.base / ("filter-" + str(self.filter_count))
        self.filter_count += 1
        script = marker.with_name("tripwire-" + marker.name + ".py")
        script.write_text(
            "from pathlib import Path\nimport sys\n"
            "Path(sys.argv[1]).write_text('invoked\\n')\n"
            "if sys.argv[2] == 'clean':\n"
            "    sys.stdout.buffer.write(sys.stdin.buffer.read())\n",
            encoding="utf-8",
        )
        command = shlex.join([sys.executable, str(script), str(marker), kind])
        self.git(root, "config", "filter.tripwire." + kind, command)
        return marker, command

    def nested_modules(self):
        leaf_origin = self.new_source("leaf-origin")
        middle_origin = self.new_source("middle-origin")
        self.git(middle_origin, "submodule", "add", "-q", str(leaf_origin), "deps/leaf")
        self.git(middle_origin, "commit", "-qam", "record nested module")
        self.git(self.root, "submodule", "add", "-q", str(middle_origin), "deps/middle")
        self.git(self.root, "commit", "-qam", "record parent module")
        self.git(self.root, "submodule", "update", "--init", "--recursive", "-q")
        middle = self.root / "deps/middle"
        return middle, middle / "deps/leaf"

    def test_clean_source_reports_exact_identity_without_mutation(self):
        index = self.root / ".git/index"
        before_index = (index.read_bytes(), index.stat().st_mtime_ns)
        before_files = {name: (self.root / name).read_bytes() for name in SOURCE_FILES}
        report = self.observe()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(report["revision"], self.git(self.root, "rev-parse", "HEAD"))
        self.assertEqual(report["tree"], self.git(self.root, "rev-parse", "HEAD^{tree}"))
        self.assertIs(report["dirty"], False)
        self.assertTrue(report["clean"])
        self.assertEqual(report["submodules"]["observed_count"], 0)
        self.assertEqual(before_index, (index.read_bytes(), index.stat().st_mtime_ns))
        self.assertEqual(before_files,
                         {name: (self.root / name).read_bytes() for name in SOURCE_FILES})

    def test_tracked_untracked_and_staged_changes_block(self):
        for kind in ("tracked", "untracked", "staged"):
            with self.subTest(kind=kind):
                root = self.new_source(kind)
                name = "private-new-input" if kind == "untracked" else "configure"
                (root / name).write_text("changed input\n", encoding="utf-8")
                if kind == "staged":
                    self.git(root, "add", "configure")
                report = self.observe(root)
                self.assert_blocked(report)
                self.assertIs(report["dirty"], True)
                self.assertFalse(report["clean"])
                self.assertNotIn("private-new-input", json.dumps(report))

    def test_staged_change_with_restored_worktree_still_blocks(self):
        path = self.root / "configure"
        path.write_text("staged input\n", encoding="utf-8")
        self.git(self.root, "add", "configure")
        path.write_text(SOURCE_FILES["configure"], encoding="utf-8")
        report = self.observe()
        self.assert_blocked(report)
        self.assertIs(report["dirty"], True)

    def test_executable_mode_change_blocks_without_a_content_change(self):
        (self.root / "configure").chmod(0o755)
        report = self.observe()
        self.assert_blocked(report)
        self.assertIs(report["dirty"], True)

    def test_ignored_generated_output_preserves_clean_source(self):
        output = self.root / "build64/result.o"
        output.parent.mkdir()
        output.write_bytes(b"ignored generated output")
        report = self.observe()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertIs(report["dirty"], False)

    def test_subdirectory_cannot_be_observed_as_the_source_root(self):
        self.assert_blocked(self.observe(self.root / "ci"))

    def test_observer_uses_no_worktree_conversion_commands(self):
        real_git = shutil.which("git")
        self.assertIsNotNone(real_git)
        binaries = self.base / "audit-bin"
        binaries.mkdir()
        audit = self.base / "git-commands.jsonl"
        shim = binaries / "git"
        shim.write_text(
            "#!" + sys.executable + "\nimport json,os,sys\n"
            "with open(" + repr(str(audit)) + ", 'a') as stream:\n"
            "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "os.execv(" + repr(real_git) + ", [" + repr(real_git) + "] + sys.argv[1:])\n",
            encoding="utf-8",
        )
        shim.chmod(0o755)
        report = self.observe(environment={
            "PATH": str(binaries) + os.pathsep + os.environ.get("PATH", ""),
        })
        self.assertEqual(report["outcome"], "pass", report)
        commands = [json.loads(line) for line in audit.read_text().splitlines()]
        self.assertTrue(commands)
        unsafe = {"status", "submodule", "diff", "diff-files", "diff-index",
                  "hash-object", "checkout", "update-index", "read-tree"}
        self.assertFalse(any(unsafe.intersection(command) for command in commands), commands)

    def test_configured_clean_and_process_filters_do_not_execute(self):
        for kind in ("clean", "process"):
            with self.subTest(kind=kind):
                root = self.new_source("configured-" + kind)
                marker, _ = self.install_filter(root, kind)
                (root / "payload.dat").write_text("modified payload\n", encoding="utf-8")
                report = self.observe(root)
                self.assertFalse(marker.exists(), "a configured Git filter was executed")
                self.assert_blocked(report)

    def test_unused_filter_configuration_still_fails_closed(self):
        for kind in ("clean", "process"):
            with self.subTest(kind=kind):
                root = self.new_source("unused-" + kind)
                self.git(root, "config", "filter.unused." + kind, "")
                self.assert_blocked(self.observe(root))

    def test_assume_unchanged_and_skip_worktree_flags_fail_closed(self):
        for flag in ("assume-unchanged", "skip-worktree"):
            for changed in (False, True):
                with self.subTest(flag=flag, changed=changed):
                    root = self.new_source(flag + str(changed))
                    self.git(root, "update-index", "--" + flag, "configure")
                    if changed:
                        (root / "configure").write_text("hidden edit\n", encoding="utf-8")
                    self.assert_blocked(self.observe(root))

    def test_version_and_gitmodules_fifos_fail_promptly(self):
        for name in ("VERSION", ".gitmodules"):
            with self.subTest(name=name):
                root = self.new_source("fifo-" + name)
                (root / name).unlink()
                os.mkfifo(root / name)
                self.assert_blocked(self.observe(root))

    def test_committed_oversized_source_inputs_fail_promptly(self):
        for name in ("VERSION", ".gitmodules", "configure"):
            with self.subTest(name=name):
                root = self.new_source("oversized-" + name)
                with (root / name).open("a", encoding="utf-8") as stream:
                    stream.write("#" + "x" * (1024 * 1024) + "\n")
                self.git(root, "add", name)
                self.git(root, "commit", "-qm", "record oversized inert input")
                self.assert_blocked(self.observe(root))

    def test_symlinked_metadata_and_source_inputs_fail_promptly(self):
        for name in ("VERSION", ".gitmodules", "configure"):
            with self.subTest(name=name):
                root = self.new_source("symlink-" + name)
                target = root / "metadata-copy"
                target.write_bytes((root / name).read_bytes())
                (root / name).unlink()
                (root / name).symlink_to(target.name)
                if name != ".gitmodules":
                    self.git(root, "add", name, target.name)
                    self.git(root, "commit", "-qm", "record inert source symlink")
                self.assert_blocked(self.observe(root))

    def test_symlinked_metadata_to_fifos_fails_promptly(self):
        for name in ("VERSION", ".gitmodules"):
            with self.subTest(name=name):
                root = self.new_source("symlink-fifo-" + name)
                os.mkfifo(root / "metadata-pipe")
                (root / name).unlink()
                (root / name).symlink_to("metadata-pipe")
                self.assert_blocked(self.observe(root))

    def test_ambient_git_directory_and_worktree_cannot_redirect_identity(self):
        decoy = self.new_source("decoy")
        (decoy / "configure").write_text("different source\n", encoding="utf-8")
        self.git(decoy, "commit", "-qam", "different identity")
        report = self.observe(environment={
            "GIT_DIR": str(decoy / ".git"), "GIT_WORK_TREE": str(decoy),
            "GIT_INDEX_FILE": str(decoy / ".git/index"),
            "GIT_COMMON_DIR": str(decoy / ".git"),
        })
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(report["revision"], self.git(self.root, "rev-parse", "HEAD"))
        self.assertNotEqual(report["revision"], self.git(decoy, "rev-parse", "HEAD"))

    def test_ambient_git_config_cannot_inject_filters_or_redirect_worktree(self):
        decoy = self.new_source("config-decoy")
        marker, command = self.install_filter(decoy, "clean")
        config = self.base / "injected.gitconfig"
        config.write_text("[filter \"tripwire\"]\n\tclean = " + json.dumps(command) + "\n",
                          encoding="utf-8")
        (self.root / "payload.dat").write_text(SOURCE_FILES["payload.dat"], encoding="utf-8")
        for variables in ({
                "GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "filter.tripwire.clean",
                "GIT_CONFIG_VALUE_0": command, "GIT_CONFIG_KEY_1": "core.worktree",
                "GIT_CONFIG_VALUE_1": str(decoy),
            }, {
                "GIT_CONFIG": str(config), "GIT_CONFIG_GLOBAL": str(config),
                "GIT_CONFIG_SYSTEM": str(config),
                "GIT_CONFIG_PARAMETERS": shlex.quote("filter.tripwire.clean=" + command),
            }):
            with self.subTest(variables=tuple(variables)):
                report = self.observe(environment=variables)
                self.assertFalse(marker.exists(), "an ambient Git filter was executed")
                self.assertEqual(report["outcome"], "pass", report)
                self.assertEqual(report["revision"], self.git(self.root, "rev-parse", "HEAD"))

    def test_recursive_modules_are_observed_at_recorded_revisions(self):
        self.nested_modules()
        report = self.observe()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(report["submodules"]["observed_count"], 2)
        self.assertEqual(report["submodules"]["initialized_count"], 2)
        self.assertTrue(report["submodules"]["at_recorded_revisions"])

    def test_ambient_git_redirect_cannot_hide_recursive_modules(self):
        self.nested_modules()
        decoy = self.new_source("module-decoy")
        report = self.observe(environment={
            "GIT_DIR": str(decoy / ".git"), "GIT_WORK_TREE": str(decoy),
            "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.worktree",
            "GIT_CONFIG_VALUE_0": str(decoy),
        })
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(report["submodules"]["observed_count"], 2)
        self.assertEqual(report["revision"], self.git(self.root, "rev-parse", "HEAD"))

    def test_dirty_recursive_module_blocks(self):
        _, leaf = self.nested_modules()
        (leaf / "configure").write_text("nested edit\n", encoding="utf-8")
        self.assert_blocked(self.observe())

    def test_untracked_recursive_module_input_blocks(self):
        _, leaf = self.nested_modules()
        (leaf / "private-nested-input").write_text("nested input\n", encoding="utf-8")
        report = self.observe()
        self.assert_blocked(report)
        self.assertNotIn("private-nested-input", json.dumps(report))

    def test_uninitialized_recursive_module_blocks(self):
        middle, _ = self.nested_modules()
        self.git(middle, "submodule", "deinit", "-f", "deps/leaf")
        self.assert_blocked(self.observe())

    def test_recursive_module_revision_mismatch_blocks(self):
        _, leaf = self.nested_modules()
        (leaf / "configure").write_text("new nested revision\n", encoding="utf-8")
        self.git(leaf, "commit", "-qam", "different nested revision")
        self.assert_blocked(self.observe())

    def test_nested_filter_is_rejected_before_recursive_status(self):
        _, leaf = self.nested_modules()
        for kind in ("clean", "process"):
            with self.subTest(kind=kind):
                marker, _ = self.install_filter(leaf, kind)
                (leaf / "payload.dat").write_text("modified payload\n", encoding="utf-8")
                try:
                    report = self.observe()
                    self.assertFalse(marker.exists(), "a nested Git filter was executed")
                    self.assert_blocked(report)
                finally:
                    self.git(leaf, "config", "--unset", "filter.tripwire." + kind)

    def test_nested_hidden_index_flags_fail_closed(self):
        _, leaf = self.nested_modules()
        for flag in ("assume-unchanged", "skip-worktree"):
            with self.subTest(flag=flag):
                self.git(leaf, "update-index", "--" + flag, "configure")
                self.assert_blocked(self.observe())
                self.git(leaf, "update-index", "--no-" + flag, "configure")

    def test_nested_gitmodules_fifo_fails_promptly(self):
        _, leaf = self.nested_modules()
        (leaf / ".gitmodules").unlink()
        os.mkfifo(leaf / ".gitmodules")
        self.assert_blocked(self.observe())


if __name__ == "__main__":
    unittest.main()
