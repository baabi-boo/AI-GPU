# SPDX-License-Identifier: Apache-2.0
"""Host runner boundary tests; synthetic processes are not parent-run evidence."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import p06_simulator_parent as parent


EXPECTED_RESULT = {"outcome": "fail", "exit_code": 1, "reason": "nonzero_exit",
                   "process_started": True, "cleanup_complete": True}


def failure(group):
    return "FAIL simulator-completion " + group + ": " + parent.MARKER + "\n"


class ReplayFixture:
    """Real retained files/identities with a synthetic local Git/compiler process."""

    def __enter__(self):
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="p06-parent-policy-")))
        self.source = self.root / "source"
        self.source.mkdir()
        for name in parent.INPUTS:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture source " + name + "\n", encoding="utf-8")
        self.parent_bytes = {name: (self.source / name).read_bytes() for name in parent.PARENT_INPUTS}
        for name in parent.PRODUCTION + parent.CONTEXT[:2]:
            self.parent_bytes[name] = b"fixture parent production " + name.encode() + b"\n"
        self.tool_paths = {}
        for name in (*parent.HOST_TOOLS, "compiler", "sys.executable", "configure-python3"):
            path = self.root / ("tool-" + name)
            path.write_text("fixture host tool " + name + "\n", encoding="utf-8")
            path.chmod(0o700)
            self.tool_paths[name] = path
        self.support = self.root / "compiler-support"
        self.support.write_text("fixture compiler support\n", encoding="utf-8")
        self.runtime = self.root / "runtime-library"
        self.runtime.write_text("fixture runtime dependency\n", encoding="utf-8")
        self.paths = {"source": self.source, "work": self.root / "work", "output": self.root / "output"}
        self.results, self.logs, self.calls = {}, {}, []
        self.after_command = lambda name: None
        self.config = "XLEN ?= 64\nPROFILE ?= p02-tfr\n"
        self.stack.enter_context(mock.patch.object(parent, "LOADED", parent.identities(self.source, parent.HELPERS)))
        self.stack.enter_context(mock.patch.object(parent, "tools_snapshot", side_effect=self.tools))
        self.resource_mock = self.stack.enter_context(mock.patch.object(parent, "resources", return_value={
            "available_memory_bytes": 8 * parent.GIB,
            "free_disk_bytes": {name: 8 * parent.GIB for name in self.paths}}))
        self.process = self.stack.enter_context(mock.patch.object(parent, "run_bounded", side_effect=self.command))
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    def tools(self, environment, compiler):
        return {name: parent.file_identity(path) for name, path in self.tool_paths.items()}

    def run(self, *extra):
        argv = ["--source-dir", str(self.source), "--work-dir", str(self.paths["work"]),
                "--output", str(self.paths["output"]), *extra]
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = parent.main(argv)
        report = self.paths["output"] / "report.json"
        return code, json.loads(report.read_text(encoding="utf-8")) if report.is_file() else None

    def command(self, argv, cwd, environment, log, **budget):
        name = log.stem
        self.calls.append({"id": name, "argv": argv, "cwd": str(cwd), "environment": environment, **budget})
        result = {"outcome": "pass", "exit_code": 0, "reason": None, "process_started": True,
                  "cleanup_complete": True, "duration_seconds": 0.01, "peak_rss_bytes": 1024}
        content = b"fixture command\n"
        if name == "candidate-revision":
            content = ("a" * 40 + "\n").encode()
        elif name == "parent-revision":
            content = (parent.PARENT + "\n").encode()
        elif name == "parent-blob-identities":
            content = "".join(hashlib.sha1(b"blob " + str(len(value)).encode() + b"\0" + value).hexdigest() + "\n"
                              for value in self.parent_bytes.values()).encode()
        elif name.startswith("parent-source-"):
            content = self.parent_bytes[parent.PARENT_INPUTS[int(name.rsplit("-", 1)[1])]]
        elif name.startswith("compiler-support-"):
            content = (str(self.support) + "\n").encode()
        elif name.startswith("dependencies-"):
            content = ("libfixture.so => " + str(self.runtime) + " (0x1234)\n").encode()
        elif name.startswith("run-"):
            content = failure(argv[1]).encode()
            result.update(EXPECTED_RESULT)
        result.update(self.results.get(name, {}))
        if result["outcome"] == "pass":
            if name == "configure-rv64-p02-tfr":
                for relative in parent.GENERATED:
                    path = cwd / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("fixture generated " + relative + "\n", encoding="utf-8")
                (cwd / "config.mk").write_text(self.config, encoding="utf-8")
            elif name.startswith("build-"):
                binary = Path(argv[argv.index("-o") + 1])
                binary.write_text("fixture compiled binary " + name + "\n", encoding="utf-8")
                binary.chmod(0o700)
        content = self.logs.get(name, content)
        log.write_bytes(content.encode() if isinstance(content, str) else content)
        result.update(log_sha256=parent.digest(log), log_size_bytes=log.stat().st_size)
        self.after_command(name)
        return result


class ParentAssertionTests(unittest.TestCase):
    def test_tool_inventory_binds_sys_executable_and_the_configure_interpreter(self):
        with tempfile.TemporaryDirectory(prefix="p06-parent-tools-") as directory:
            tool = Path(directory) / "installed-tool"
            tool.write_text("fixture tool\n", encoding="utf-8")
            environment = {"PATH": directory}
            with mock.patch.object(parent.shutil, "which", side_effect=lambda name, **kwargs:
                                   parent.sys.executable if name == "python3" else str(tool)):
                identities = parent.tools_snapshot(environment, "c++")
            self.assertEqual(identities["sys.executable"], parent.file_identity(parent.sys.executable))
            self.assertEqual(identities["configure-python3"]["sha256"], identities["sys.executable"]["sha256"])
            with mock.patch.object(parent.shutil, "which", return_value=str(tool)), self.assertRaisesRegex(
                    ValueError, "interpreter differs from sys.executable"):
                parent.tools_snapshot(environment, "c++")

    def test_exact_behavioral_failures_preserve_the_nonzero_raw_outcome(self):
        original = copy.deepcopy(EXPECTED_RESULT)
        for group in parent.GROUPS:
            with self.subTest(group=group):
                observed = parent.verify_expected_failure(failure(group), group, EXPECTED_RESULT)
                self.assertEqual(observed["assertion"], parent.MARKER)
                self.assertEqual(EXPECTED_RESULT, original)

    def test_timeout_build_failure_cleanup_problem_or_no_process_cannot_count(self):
        changes = ({"outcome": "pass"}, {"outcome": "blocked"}, {"exit_code": 0}, {"exit_code": 2},
                   {"exit_code": -15}, {"reason": "timeout"}, {"reason": "memory_limit"},
                   {"reason": "disk_reserve"}, {"process_started": False}, {"cleanup_complete": False})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                parent.verify_expected_failure(failure(parent.GROUPS[0]), parent.GROUPS[0],
                                               dict(EXPECTED_RESULT, **change))

    def test_unrelated_truncated_duplicated_and_wrong_group_markers_are_rejected(self):
        wanted = failure("standard_exception")
        for text in ("", "compiler failed\n", wanted.rstrip(), wanted * 2,
                     failure("unknown_exception"), wanted + "PASS simulator-completion\n",
                     wanted.replace(parent.MARKER, "completion remained pending after released worker")):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parent.verify_expected_failure(text, "standard_exception", EXPECTED_RESULT)


class ParentReplayPolicyTests(unittest.TestCase):
    def test_local_replace_refs_cannot_change_pinned_parent_sources(self):
        git = parent.shutil.which("git")
        self.assertIsNotNone(git, "Git is required for the pinned-parent boundary test")
        bounded = parent.run_bounded
        with ReplayFixture() as fixture:
            candidate_bytes = {name: (fixture.source / name).read_bytes() for name in parent.PARENT_INPUTS}
            git_environment = {"PATH": parent.os.environ.get("PATH", parent.os.defpath), "LC_ALL": "C",
                               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": parent.os.devnull}

            def git_command(*argv):
                return subprocess.run([git, "-C", str(fixture.source),
                                       "-c", "user.name=Parent replay test",
                                       "-c", "user.email=parent-replay@example.invalid", *argv],
                                      env=git_environment, check=True, capture_output=True, timeout=10).stdout

            git_command("init", "--quiet")
            for name, content in fixture.parent_bytes.items():
                (fixture.source / name).write_bytes(content)
            git_command("add", "--", *parent.PARENT_INPUTS)
            pinned = git_command("commit-tree", git_command("write-tree").decode().strip(),
                                 "-m", "Pinned parent").decode().strip()
            changed = parent.PRODUCTION[0]
            pinned_blob = git_command("rev-parse", pinned + ":" + changed).decode().strip()
            substituted = b"replacement transport bytes\n"
            (fixture.source / changed).write_bytes(substituted)
            git_command("add", "--", changed)
            replacement = git_command("commit-tree", git_command("write-tree").decode().strip(),
                                      "-m", "Local replacement").decode().strip()
            git_command("update-ref", "HEAD", pinned)
            git_command("replace", pinned, replacement)
            self.assertEqual(git_command("rev-parse", pinned + "^{commit}").decode().strip(), pinned)
            self.assertEqual(git_command("show", pinned + ":" + changed), substituted)
            replacement_blob = git_command("rev-parse", pinned + ":" + changed).decode().strip()
            self.assertNotEqual(replacement_blob, pinned_blob)
            self.assertEqual(replacement_blob, hashlib.sha1(
                b"blob " + str(len(substituted)).encode() + b"\0" + substituted).hexdigest())
            for name, content in candidate_bytes.items():
                (fixture.source / name).write_bytes(content)
            fixture.tool_paths["git"] = Path(git)
            git_calls = []

            def command(argv, cwd, environment, log, **budget):
                if argv[0] == git:
                    git_calls.append({"id": log.stem, "environment": dict(environment)})
                    return bounded(argv, cwd, environment, log, **budget)
                return fixture.command(argv, cwd, environment, log, **budget)

            fixture.process.side_effect = command
            with mock.patch.object(parent, "PARENT", pinned), mock.patch.dict(
                    parent.os.environ, {"GIT_NO_REPLACE_OBJECTS": "0"}):
                code, report = fixture.run()
            self.assertEqual((code, report["outcome"]), (0, "pass"), report.get("reason"))
            self.assertEqual(report["parent_revision"], pinned)
            self.assertEqual(report["parent_git_blobs"][changed], pinned_blob)
            self.assertEqual((fixture.paths["output"] / "inputs/parent" / changed).read_bytes(),
                             fixture.parent_bytes[changed])
            self.assertEqual(report["environment"]["GIT_NO_REPLACE_OBJECTS"], "1")
            self.assertTrue(git_calls)
            for call in git_calls + fixture.calls:
                self.assertEqual(call["environment"]["GIT_NO_REPLACE_OBJECTS"], "1", call["id"])

    def test_changed_executing_helper_blocks_before_any_process(self):
        with ReplayFixture() as fixture:
            (fixture.source / parent.HELPERS[-1]).write_text("changed after helper import\n", encoding="utf-8")
            code, report = fixture.run()
            self.assertEqual((code, report["outcome"]), (1, "blocked"))
            self.assertIn("executing helpers differ", report["reason"])
            fixture.process.assert_not_called()

    def test_all_eight_cells_compile_real_old_sources_with_the_shared_argv_producer(self):
        with ReplayFixture() as fixture:
            code, report = fixture.run()
            self.assertEqual((code, report["outcome"]), (0, "pass"), report.get("reason"))
            self.assertTrue(report["full_matrix_completed"])
            self.assertFalse(report["native_execution"])
            self.assertFalse(report["qualified"])
            self.assertFalse(report["acceptance_claimed"])
            expected = {(backend, group, memory) for backend in parent.BACKENDS
                        for group in parent.GROUPS for memory in parent.MEMORIES}
            self.assertEqual({(row["backend"], row["group"], row["memory"]) for row in report["cells"]}, expected)
            for row in report["cells"]:
                self.assertEqual(row["outcome"], "expected_failure")
                self.assertEqual((row["result"]["outcome"], row["result"]["exit_code"]), ("fail", 1))
            for label in ("source", "parent", "tools", "generated", "extra_tools"):
                self.assertEqual(report[label + "_before"], report[label + "_after"])
            self.assertTrue(all(report["shared_parent_candidate_equal"].values()))
            for backend in parent.BACKENDS:
                build = next(row for row in fixture.calls if row["id"] == "build-" + backend)
                self.assertIn(str(fixture.paths["work"] / "parent-sources/sw/runtime" / backend / "vortex.cpp"), build["argv"])
                self.assertIn(str(fixture.source / "sim/common/cmd_processor.cpp"), build["argv"])
                self.assertIn(str(fixture.source / "ci/project/fixtures/simulator_completion/main.cpp"), build["argv"])
                self.assertIn("-fsanitize=undefined", build["argv"])
                self.assertEqual(build["timeout_seconds"], 60)
                self.assertEqual(report["builds"][backend]["binary_before"], report["builds"][backend]["binary_after"])
            for call in fixture.calls:
                self.assertEqual(call["min_free_bytes"], parent.GIB)
                self.assertEqual(call["max_rss_bytes"], parent.GIB)
                self.assertEqual(call["max_log_bytes"], parent.MIB)
                self.assertLessEqual(call["timeout_seconds"], 60)
                if call["id"].startswith("run-"):
                    self.assertEqual(call["timeout_seconds"], 10)
            for command in report["commands"]:
                path = fixture.paths["output"] / command["log"]
                self.assertEqual(parent.digest(path), command["result"]["log_sha256"])
            self.assertEqual(report["sys_executable"], parent.sys.executable)
            self.assertEqual((fixture.paths["work"] / "tool-bin/python3").resolve(), Path(parent.sys.executable).resolve())

    def test_existing_or_overlapping_paths_preserve_old_evidence_without_starting(self):
        with ReplayFixture() as fixture:
            output = fixture.paths["output"]
            output.mkdir()
            (output / "report.json").write_text('{"retained": true}\n', encoding="utf-8")
            code, report = fixture.run()
            self.assertEqual((code, report), (2, {"retained": True}))
            self.assertFalse(fixture.paths["work"].exists())
            fixture.process.assert_not_called()
        for argument, value in (("--work-dir", "source"), ("--output", "source/new"), ("--output", "work")):
            with self.subTest(argument=argument, value=value), ReplayFixture() as fixture:
                code, report = fixture.run(argument, str(fixture.root / value))
                self.assertEqual((code, report), (2, None))
                fixture.process.assert_not_called()

    def test_changed_shared_cp_callbacks_or_configuration_block_before_building(self):
        for name in ("sim/common/cmd_processor.cpp", "sw/runtime/common/callbacks.inc", "VX_config.toml"):
            with self.subTest(name=name), ReplayFixture() as fixture:
                fixture.parent_bytes[name] += b"different pinned source\n"
                code, report = fixture.run()
                self.assertEqual((code, report["outcome"]), (1, "fail"))
                self.assertFalse(any(row["id"].startswith("build-") for row in fixture.calls))
                self.assertFalse(report["shared_parent_candidate_equal"][name])

    def test_git_blob_mismatch_blocks_compilation_and_retains_extraction(self):
        with ReplayFixture() as fixture:
            fixture.logs["parent-source-00"] = "content substituted after object identification\n"
            code, report = fixture.run()
            self.assertEqual((code, report["outcome"]), (1, "fail"))
            self.assertIn("Git blob", report["reason"])
            self.assertFalse(any(row["id"].startswith("build-") for row in fixture.calls))
            self.assertTrue((fixture.paths["output"] / "logs/parent-source-00.log").is_file())

    def test_build_failure_with_the_marker_is_never_behavioral_evidence(self):
        with ReplayFixture() as fixture:
            fixture.results["build-simx"] = dict(EXPECTED_RESULT)
            fixture.logs["build-simx"] = failure("standard_exception")
            code, report = fixture.run()
            self.assertEqual((code, report["outcome"]), (1, "fail"))
            self.assertFalse(report["full_matrix_completed"])
            self.assertTrue(all(row["outcome"] == "blocked" for row in report["cells"]))
            self.assertFalse(any(row["id"].startswith("run-") for row in fixture.calls))
            self.assertTrue((fixture.paths["output"] / "logs/build-simx.log").is_file())

    def test_one_timeout_unexpected_success_or_unrelated_assertion_invalidates_matrix(self):
        for condition in ("timeout", "success", "unrelated"):
            with self.subTest(condition=condition), ReplayFixture() as fixture:
                name = "run-simx-standard_exception-ram"
                if condition == "timeout":
                    fixture.results[name] = {"reason": "timeout", "exit_code": -15}
                elif condition == "success":
                    fixture.results[name] = {"outcome": "pass", "exit_code": 0, "reason": None}
                else:
                    fixture.logs[name] = "FAIL simulator-completion standard_exception: unrelated\n"
                code, report = fixture.run()
                self.assertEqual((code, report["outcome"]), (1, "fail"))
                self.assertFalse(report["full_matrix_completed"])
                self.assertEqual(report["cells"][0]["outcome"], "fail")
                self.assertEqual(sum(row["outcome"] == "expected_failure" for row in report["cells"]), 7)
                self.assertTrue((fixture.paths["output"] / ("logs/" + name + ".log")).is_file())

    def test_source_parent_binary_tool_config_and_retained_log_drift_invalidate_replay(self):
        for what in ("source", "parent", "binary", "tool", "config", "log", "retained"):
            with self.subTest(what=what), ReplayFixture() as fixture:
                def mutate(command):
                    if command != "run-simx-standard_exception-ram":
                        return
                    targets = {"source": fixture.source / "sim/common/cmd_processor.cpp",
                               "parent": fixture.paths["work"] / "parent-sources/sw/runtime/simx/vortex.cpp",
                               "binary": fixture.paths["work"] / "rv64-p02-tfr/simx-completion",
                               "tool": fixture.support,
                               "config": fixture.paths["work"] / "rv64-p02-tfr/sw/VX_config.h",
                               "log": fixture.paths["output"] / "logs/version-compiler.log",
                               "retained": fixture.paths["output"] / "inputs/candidate/sim/common/cmd_processor.cpp"}
                    with targets[what].open("ab") as stream:
                        stream.write(b"changed after execution\n")
                fixture.after_command = mutate
                code, report = fixture.run()
                self.assertEqual((code, report["outcome"]), (1, "fail"), report.get("reason"))
                self.assertFalse(report["full_matrix_completed"])
                self.assertIn("changed", report["reason"])
                self.assertEqual(report["state"], "finished")

    def test_preflight_resource_shortfall_is_retained_without_running_a_process(self):
        for kind in ("disk", "memory"):
            with self.subTest(kind=kind), ReplayFixture() as fixture:
                values = {"available_memory_bytes": parent.GIB,
                          "free_disk_bytes": {name: parent.GIB for name in fixture.paths}}
                if kind == "disk":
                    values["free_disk_bytes"]["work"] -= 1
                else:
                    values["available_memory_bytes"] -= 1
                fixture.resource_mock.return_value = values
                code, report = fixture.run()
                self.assertEqual(code, 1)
                self.assertNotEqual(report["outcome"], "pass")
                self.assertFalse(report["full_matrix_completed"])
                fixture.process.assert_not_called()

    def test_second_backend_cannot_replace_an_already_bound_runtime_library_identity(self):
        with ReplayFixture() as fixture:
            def mutate(command):
                if command == "build-rtlsim":
                    fixture.runtime.write_text("runtime library replaced between backend builds\n", encoding="utf-8")
            fixture.after_command = mutate
            code, report = fixture.run()
            self.assertEqual((code, report["outcome"]), (1, "fail"))
            self.assertFalse(report["full_matrix_completed"])
            self.assertIn("dependency changed", report["reason"])
            self.assertFalse(any(row["id"].startswith("run-rtlsim-") for row in fixture.calls))

    def test_configure_must_actually_generate_the_declared_rv64_profile(self):
        for config in ("XLEN ?= 32\nPROFILE ?= p02-tfr\n", "XLEN ?= 64\nPROFILE ?= other\n"):
            with self.subTest(config=config), ReplayFixture() as fixture:
                fixture.config = config
                code, report = fixture.run()
                self.assertEqual((code, report["outcome"]), (1, "fail"))
                self.assertFalse(any(row["id"].startswith("build-") for row in fixture.calls))


if __name__ == "__main__":
    unittest.main()
