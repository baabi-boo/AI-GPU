# SPDX-License-Identifier: Apache-2.0
"""Real-filesystem checks for governance receipts and CLI orchestration."""

from copy import deepcopy
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

import governance_run as runner


RUNNER_PATH = Path(runner.__file__).resolve()


class _Workspace(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="governance-receipts-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.source = self.base / "source"
        (self.source / "ci/project").mkdir(parents=True)
        self.tracked = self.source / "tracked.txt"
        self.tracked.write_text("committed input\n", encoding="utf-8")
        self.output = self.base / "run"
        self.git_executable = shutil.which("git")
        self.assertIsNotNone(self.git_executable, "the runner requires Git")
        self.process_environment = {
            key: value for key, value in os.environ.items() if not key.startswith("GIT_")
        }
        self.process_environment.update(
            GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
            GIT_TERMINAL_PROMPT="0", PYTHONDONTWRITEBYTECODE="1")
        self.git("init", "-q")
        self.git("add", "tracked.txt")
        self.commit("initial source")

    def git(self, *arguments):
        return subprocess.run(
            [self.git_executable, "-c", "core.hooksPath=" + os.devnull, *arguments],
            cwd=self.source, env=self.process_environment, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10,
        ).stdout.strip()

    def commit(self, message):
        self.git("-c", "user.name=Governance fixture", "-c",
                 "user.email=governance-fixture@example.invalid", "-c",
                 "commit.gpgsign=false", "commit", "-qm", message)

    @staticmethod
    def read_json(path):
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def tool_identity(path):
        content = path.read_bytes()
        return {"path": str(path), "resolved_path": str(path.resolve()),
                "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}

    def environment_fixture(self, python_executable=None):
        binary = self.base / "tools/bin"
        native = self.base / "tools/native"
        binary.mkdir(parents=True)
        native.mkdir()
        self.command_marker = self.base / "receipt-command-executed"
        poison = "printf executed > " + shlex.quote(str(self.command_marker))
        for name in sorted(runner.REQUIRED_ENVIRONMENT_TOOLS):
            if name == "git":
                (binary / name).symlink_to(Path(self.git_executable).resolve())
                continue
            if python_executable is not None and name in {"python", "python3"}:
                (binary / name).symlink_to(Path(python_executable).resolve())
                continue
            target = native / name
            target.write_text("#!/bin/sh\n" + poison + "\nexit 97\n", encoding="utf-8")
            target.chmod(0o755)
            (binary / name).symlink_to(target)
        interpreter = binary / "python"
        receipt = {
            "schema_version": 1, "status": "ready", "interpreter": str(interpreter),
            "environment": {"PATH": os.pathsep.join((str(binary), "/usr/bin", "/bin"))},
            "tools": {name: self.tool_identity(binary / name)
                      for name in runner.REQUIRED_ENVIRONMENT_TOOLS},
            "cmake_selection": {"resolution": "native",
                                "requested": self.tool_identity(binary / "cmake"),
                                "native": self.tool_identity(native / "cmake")},
            "commands": [{"argv": ["/bin/sh", "-c", poison],
                          "command": poison, "shell": True}],
        }
        path = self.base / "environment.json"
        self.write_receipt(path, receipt)
        return path, receipt, interpreter

    @staticmethod
    def write_receipt(path, receipt):
        path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")

    def run_main(self, *bodies, output=None, receipt=None, interpreter=None,
                 discover_hook=None, log_limit=None, active_path=None):
        class Probe(unittest.TestCase):
            def __init__(self, index, body):
                super().__init__("runTest")
                self.index, self.body = index, body

            def id(self):
                return "receipt_fixture.Probe.test_" + str(self.index)

            def runTest(self):
                self.body()

        class SyntheticLoader:
            def __init__(self):
                self.errors = []
                self.calls = []

            def discover(self, start_directory, pattern):
                self.calls.append((start_directory, pattern))
                if discover_hook is not None:
                    discover_hook()
                return unittest.TestSuite(Probe(index, body)
                                          for index, body in enumerate(bodies))

        if receipt is None:
            receipt, _, fixture_interpreter = self.environment_fixture()
            if interpreter is None:
                interpreter = fixture_interpreter
        output = self.output if output is None else output
        loader = SyntheticLoader()
        stdout, stderr = io.StringIO(), io.StringIO()
        arguments = ["--output-dir", str(output)]
        if receipt is not None:
            arguments.extend(("--environment-receipt", str(receipt)))
        original_cwd = Path.cwd()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(runner, "ROOT", self.source))
            stack.enter_context(mock.patch.object(runner.unittest, "TestLoader", return_value=loader))
            stack.enter_context(contextlib.redirect_stdout(stdout))
            stack.enter_context(contextlib.redirect_stderr(stderr))
            if interpreter is not None:
                stack.enter_context(mock.patch.object(runner.sys, "executable", str(interpreter)))
            if receipt is not None and interpreter is not None:
                path = active_path if active_path is not None else os.pathsep.join(
                    (str(Path(interpreter).parent), "/usr/bin", "/bin"))
                stack.enter_context(mock.patch.dict(os.environ, {"PATH": path}))
            if log_limit is not None:
                stack.enter_context(mock.patch.object(runner, "MAX_LOG_BYTES", log_limit))
            code = runner.main(arguments)
        self.assertEqual(Path.cwd(), original_cwd)
        return code, self.read_json(output / "summary.json"), loader, stdout.getvalue(), stderr.getvalue()

    def assert_started_only(self, output=None):
        output = self.output if output is None else output
        started = self.read_json(output / "started.json")
        self.assertEqual(started["status"], "started")
        self.assertIs(started["governance_passed"], False)
        self.assertIs(started["execution_completed"], False)
        return started

    def assert_rejected_output(self, output, receipt, expected_error):
        stderr = io.StringIO()
        with mock.patch.object(runner, "ROOT", self.source), \
                contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as rejected:
            runner.main(["--output-dir", str(output), "--environment-receipt", str(receipt)])
        self.assertEqual(rejected.exception.code, 2)
        self.assertIn("error:", stderr.getvalue())
        self.assertIn(expected_error, stderr.getvalue())
        self.assertNotIn("the following arguments are required", stderr.getvalue())


class GovernanceRunReceiptTests(_Workspace):
    def test_fresh_run_writes_started_discovery_events_log_and_complete_summary(self):
        observed = {}

        def inspect_discovery():
            observed["started"] = self.assert_started_only()
            self.assertTrue(observed["started"]["source_before"]["clean"])
            self.assertFalse((self.output / "discovered.json").exists())
            self.assertFalse((self.output / "summary.json").exists())
            self.assertEqual(Path.cwd(), self.source)

        def body():
            discovered = self.read_json(self.output / "discovered.json")
            self.assertEqual(discovered["test_ids"], ["receipt_fixture.Probe.test_0"])
            self.assertEqual(self.tracked.read_text(encoding="utf-8"), "committed input\n")
            self.assertFalse((self.output / "summary.json").exists())
            print("stdout from governed body")
            print("stderr from governed body", file=sys.stderr)

        code, summary, loader, stdout, stderr = self.run_main(body, discover_hook=inspect_discovery)
        self.assertEqual(code, 0)
        self.assertEqual(loader.calls, [("ci/project", "test_*.py")])
        self.assertEqual(set(path.name for path in self.output.iterdir()), {
            "started.json", "discovered.json", "events.jsonl", "unittest.log", "summary.json"})
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.assert_started_only(), observed["started"])
        self.assertEqual(summary["status"], "completed")
        self.assertTrue(summary["governance_passed"])
        self.assertTrue(summary["execution_completed"])
        for field in ("source_stable", "interpreter_stable", "environment_stable"):
            self.assertTrue(summary[field])
        self.assertEqual(summary["source_before"]["head"], self.git("rev-parse", "HEAD"))
        self.assertEqual(summary["source_before"]["tree"], self.git("rev-parse", "HEAD^{tree}"))
        self.assertEqual(summary["source_before"], summary["source_after"])
        self.assertEqual(summary["environment_before"], summary["environment_after"])
        self.assertEqual(set(summary["environment_before"]["tools"]),
                         runner.REQUIRED_ENVIRONMENT_TOOLS)
        self.assertEqual(summary["command"][-2:],
                         ["--environment-receipt", str(self.base / "environment.json")])
        self.assertFalse(self.command_marker.exists())
        discovered = self.read_json(self.output / "discovered.json")
        self.assertEqual(discovered["count"], 1)
        self.assertEqual(discovered["sha256"], hashlib.sha256(
            b"receipt_fixture.Probe.test_0\n").hexdigest())
        events = [json.loads(line) for line in (self.output / "events.jsonl").read_text().splitlines()]
        self.assertEqual([event["event"] for event in events], ["test_start", "test_outcome", "test_stop"])
        self.assertEqual([event["sequence"] for event in events], [1, 2, 3])
        self.assertEqual(summary["event_bytes"], (self.output / "events.jsonl").stat().st_size)
        log = (self.output / "unittest.log").read_text(encoding="utf-8")
        self.assertIn("stdout from governed body", log)
        self.assertIn("stderr from governed body", log)
        self.assertIn("stdout from governed body", stdout)
        self.assertIn("stderr from governed body", stderr)
        self.assertIn("Strict governance PASSED", stdout)
        self.assertEqual(summary["log"], {"bytes": len(log.encode("utf-8")), "truncated": False})

    def test_existing_output_directory_and_file_are_preserved_and_rejected(self):
        receipt, _, _ = self.environment_fixture()
        directory = self.base / "occupied-directory"
        directory.mkdir()
        marker = directory / "untouched"
        marker.write_bytes(b"original")
        existing_file = self.base / "occupied-file"
        existing_file.write_bytes(b"original")
        for output in (directory, existing_file):
            with self.subTest(output=output.name):
                self.assert_rejected_output(output, receipt, "File exists")
        self.assertEqual(marker.read_bytes(), b"original")
        self.assertEqual(existing_file.read_bytes(), b"original")
        self.assertEqual(list(directory.iterdir()), [marker])

    def test_output_symlinks_and_symlink_parent_are_rejected(self):
        receipt, _, _ = self.environment_fixture()
        target = self.base / "target"
        target.mkdir()
        alias = self.base / "alias"
        alias.symlink_to(target, target_is_directory=True)
        dangling = self.base / "dangling"
        dangling.symlink_to(self.base / "missing", target_is_directory=True)
        for output in (alias, alias / "child", dangling):
            with self.subTest(output=str(output)):
                self.assert_rejected_output(
                    output, receipt, "exact absolute path without symlink components")
        self.assertEqual(list(target.iterdir()), [])
        self.assertFalse((self.base / "missing").exists())
        self.assertTrue(dangling.is_symlink())

    def test_output_source_overlap_relative_path_and_traversal_are_rejected(self):
        receipt, _, _ = self.environment_fixture()
        for output, expected_error in (
                (self.source, "outside the source checkout"),
                (self.source / "receipt", "outside the source checkout"),
                (self.base, "outside the source checkout"),
                ("relative-receipt", "exact absolute path without symlink components"),
                (str(self.base / "unused") + "/../escaped",
                 "exact absolute path without symlink components")):
            with self.subTest(output=str(output)):
                self.assert_rejected_output(output, receipt, expected_error)
        self.assertFalse((self.source / "receipt").exists())
        self.assertFalse((self.base / "escaped").exists())
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_dirty_source_is_rejected_before_discovery(self):
        self.tracked.write_text("uncommitted change\n", encoding="utf-8")
        code, summary, loader, _, _ = self.run_main(lambda: self.fail("body must not run"))
        self.assertEqual(code, 1)
        self.assertFalse(loader.calls)
        self.assertFalse(summary["governance_passed"])
        self.assertFalse(summary["execution_completed"])
        self.assertFalse(summary["source_before"]["clean"])
        self.assertIn("clean source checkout", summary["errors"][0]["message"])
        self.assert_started_only()
        self.assertFalse((self.output / "discovered.json").exists())

    def test_source_change_during_execution_rejects_an_otherwise_passing_suite(self):
        def mutate():
            self.tracked.write_text("changed during run\n", encoding="utf-8")

        code, summary, _, _, _ = self.run_main(mutate)
        self.assertEqual(code, 1)
        self.assertTrue(summary["execution"]["strict_success"])
        self.assertTrue(summary["execution_completed"])
        self.assertFalse(summary["source_stable"])
        self.assertFalse(summary["source_after"]["clean"])
        self.assertFalse(summary["governance_passed"])

    def test_clean_commit_change_during_execution_still_rejects_source_identity(self):
        def replace_commit():
            self.tracked.write_text("new committed input\n", encoding="utf-8")
            self.git("add", "tracked.txt")
            self.commit("changed source during execution")

        code, summary, _, _, _ = self.run_main(replace_commit)
        self.assertEqual(code, 1)
        self.assertTrue(summary["execution"]["strict_success"])
        self.assertTrue(summary["source_after"]["clean"])
        self.assertNotEqual(summary["source_before"]["head"], summary["source_after"]["head"])
        self.assertFalse(summary["source_stable"])
        self.assertFalse(summary["governance_passed"])

    def test_changed_interpreter_bytes_reject_an_otherwise_passing_suite(self):
        path, receipt, selected_interpreter = self.environment_fixture()
        interpreter = selected_interpreter.with_name("interpreter")
        interpreter.write_bytes(b"interpreter before\n")
        interpreter.chmod(0o755)
        receipt["interpreter"] = str(interpreter)
        self.write_receipt(path, receipt)

        def mutate():
            interpreter.write_bytes(b"interpreter after!\n")

        code, summary, _, _, _ = self.run_main(mutate, receipt=path, interpreter=interpreter)
        self.assertEqual(code, 1)
        self.assertTrue(summary["source_stable"])
        self.assertTrue(summary["execution"]["strict_success"])
        self.assertTrue(summary["environment_stable"])
        self.assertFalse(summary["interpreter_stable"])
        self.assertFalse(summary["governance_passed"])
        self.assertNotEqual(summary["interpreter_before"]["executable"]["sha256"],
                            summary["interpreter_after"]["executable"]["sha256"])

    def test_discovery_exception_preserves_an_incomplete_nonpassing_receipt(self):
        def interrupted_discovery():
            raise RuntimeError("discovery stopped before returning a suite")

        code, summary, loader, _, _ = self.run_main(discover_hook=interrupted_discovery)
        self.assertEqual(code, 1)
        self.assertEqual(loader.calls, [("ci/project", "test_*.py")])
        self.assertEqual(summary["status"], "incomplete")
        self.assertFalse(summary["execution_completed"])
        self.assertFalse(summary["governance_passed"])
        self.assertEqual(summary["errors"][0]["type"], "RuntimeError")
        self.assert_started_only()
        self.assertFalse((self.output / "discovered.json").exists())
        self.assertEqual((self.output / "events.jsonl").read_bytes(), b"")

    def test_failure_retains_stdout_stderr_traceback_and_nonpassing_final_summary(self):
        def fail():
            print("stdout before intentional failure")
            print("stderr before intentional failure", file=sys.stderr)
            self.fail("intentional retained failure")

        code, summary, _, stdout, stderr = self.run_main(fail)
        self.assertEqual(code, 1)
        self.assertEqual(summary["status"], "completed")
        self.assertTrue(summary["execution_completed"])
        self.assertFalse(summary["governance_passed"])
        self.assertEqual(summary["execution"]["outcome_counts"], {"failure": 1})
        log = (self.output / "unittest.log").read_text(encoding="utf-8")
        for text in ("stdout before intentional failure", "stderr before intentional failure",
                     "Traceback", "intentional retained failure", "FAILED"):
            self.assertIn(text, log)
        self.assertIn("stdout before intentional failure", stdout)
        self.assertIn("intentional retained failure", stderr)
        self.assertIn("Strict governance FAILED", stdout)
        self.assert_started_only()

    def test_truncated_log_cannot_qualify_a_completed_successful_suite(self):
        message = "large body output " + "x" * 1024
        code, summary, _, stdout, _ = self.run_main(lambda: print(message), log_limit=256)
        self.assertEqual(code, 1)
        self.assertTrue(summary["execution_completed"])
        self.assertTrue(summary["execution"]["strict_success"])
        self.assertTrue(summary["log"]["truncated"])
        self.assertFalse(summary["governance_passed"])
        self.assertIn(message, stdout)
        self.assertNotIn(message, (self.output / "unittest.log").read_text(encoding="utf-8"))
        self.assertLessEqual((self.output / "unittest.log").stat().st_size, 256)
        self.assertEqual(summary["log"]["bytes"], (self.output / "unittest.log").stat().st_size)


class GovernanceEnvironmentReceiptTests(_Workspace):
    def test_environment_binding_hashes_real_files_without_executing_receipt_commands(self):
        path, receipt, interpreter = self.environment_fixture()
        code, summary, loader, _, _ = self.run_main(
            lambda: self.assertEqual(self.tracked.read_text(), "committed input\n"),
            receipt=path, interpreter=interpreter)
        self.assertEqual(code, 0)
        self.assertEqual(loader.calls, [("ci/project", "test_*.py")])
        self.assertTrue(summary["governance_passed"])
        self.assertTrue(summary["environment_stable"])
        self.assertEqual(summary["environment_before"], summary["environment_after"])
        bound = summary["environment_before"]
        self.assertEqual(bound["receipt_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(bound["receipt_size_bytes"], path.stat().st_size)
        self.assertEqual(set(bound["tools"]), runner.REQUIRED_ENVIRONMENT_TOOLS)
        for name, identity in receipt["tools"].items():
            self.assertEqual(bound["tools"][name]["requested_path"], identity["path"])
            self.assertEqual(bound["tools"][name]["sha256"], identity["sha256"])
        self.assertFalse(self.command_marker.exists())
        self.assertEqual(self.read_json(path), receipt)

    def test_active_path_mismatch_rejects_an_otherwise_valid_environment_receipt(self):
        path, _, interpreter = self.environment_fixture()
        code, summary, loader, _, _ = self.run_main(
            lambda: self.fail("unbound active PATH reached a body"), receipt=path,
            interpreter=interpreter, active_path="/usr/bin:/bin")
        self.assertEqual(code, 1)
        self.assertFalse(loader.calls)
        self.assertFalse(summary["governance_passed"])
        self.assertFalse(summary["execution_completed"])
        self.assertTrue(summary["errors"])
        self.assertIn("PATH", summary["errors"][0]["message"])
        self.assert_started_only()
        self.assertFalse(self.command_marker.exists())

    def test_before_and_after_tool_alias_retarget_are_rejected(self):
        path, receipt, interpreter = self.environment_fixture()
        alias = Path(receipt["tools"]["cmake"]["path"])
        original = alias.resolve()
        alternate = original.with_name("cmake-alternate")
        alternate.write_bytes(original.read_bytes())
        alternate.chmod(0o755)

        def retarget():
            alias.unlink()
            alias.symlink_to(alternate)

        for phase in ("before", "during"):
            with self.subTest(phase=phase):
                alias.unlink()
                alias.symlink_to(original)
                if phase == "before":
                    retarget()
                code, summary, loader, _, _ = self.run_main(
                    retarget, output=self.base / ("alias-" + phase),
                    receipt=path, interpreter=interpreter)
                self.assertEqual(code, 1)
                self.assertFalse(summary["governance_passed"])
                self.assertIn("tool identity changed", summary["errors"][0]["message"])
                self.assertFalse(self.command_marker.exists())
                if phase == "before":
                    self.assertFalse(loader.calls)
                    self.assertFalse(summary["execution_completed"])
                else:
                    self.assertTrue(summary["execution"]["strict_success"])
                    self.assertTrue(summary["execution_completed"])
                    self.assertEqual(summary["interpreter_before"], summary["interpreter_after"])

    def test_before_and_after_tool_byte_tampering_are_rejected(self):
        path, receipt, interpreter = self.environment_fixture()
        tool = Path(receipt["tools"]["cmake"]["resolved_path"])
        original = tool.read_bytes()

        def tamper():
            tool.write_bytes(original.replace(b"exit 97", b"exit 98"))
            self.assertEqual(tool.stat().st_size, len(original))

        for phase in ("before", "during"):
            with self.subTest(phase=phase):
                tool.write_bytes(original)
                if phase == "before":
                    tamper()
                code, summary, loader, _, _ = self.run_main(
                    tamper, output=self.base / ("bytes-" + phase),
                    receipt=path, interpreter=interpreter)
                self.assertEqual(code, 1)
                self.assertFalse(summary["governance_passed"])
                self.assertIn("tool identity changed", summary["errors"][0]["message"])
                self.assertFalse(self.command_marker.exists())
                if phase == "before":
                    self.assertFalse(loader.calls)
                else:
                    self.assertTrue(summary["execution"]["strict_success"])
                    self.assertEqual(summary["source_before"], summary["source_after"])

    def test_changed_receipt_bytes_reject_even_when_both_receipts_bind_valid_tools(self):
        path, receipt, interpreter = self.environment_fixture()

        def rewrite_receipt():
            changed = deepcopy(receipt)
            changed["note"] = "receipt changed after discovery"
            self.write_receipt(path, changed)

        code, summary, _, _, _ = self.run_main(rewrite_receipt, receipt=path, interpreter=interpreter)
        self.assertEqual(code, 1)
        self.assertTrue(summary["execution"]["strict_success"])
        self.assertTrue(summary["source_stable"])
        self.assertTrue(summary["interpreter_stable"])
        self.assertFalse(summary["environment_stable"])
        self.assertFalse(summary["governance_passed"])
        self.assertFalse(self.command_marker.exists())

    def test_invalid_environment_fields_reject_before_discovery(self):
        path, original, interpreter = self.environment_fixture()
        cases = {
            "boolean schema": lambda row: row.update(schema_version=True),
            "unknown schema": lambda row: row.update(schema_version=2),
            "not ready": lambda row: row.update(status="preparing"),
            "wrong interpreter": lambda row: row.update(interpreter="/unselected/python"),
            "wrong PATH": lambda row: row["environment"].update(PATH="/usr/bin:/bin"),
            "environment wrong type": lambda row: row.update(environment=[]),
            "incomplete tools": lambda row: row["tools"].pop("gcc"),
            "tool inventory wrong type": lambda row: row.update(tools=[]),
            "oversized inventory": lambda row: row["tools"].update(
                {"extra_" + str(index): {} for index in range(65)}),
            "relative tool": lambda row: row["tools"]["cmake"].update(path="bin/cmake"),
            "wrong tool hash": lambda row: row["tools"]["cmake"].update(sha256="0" * 64),
            "boolean tool size": lambda row: row["tools"]["cmake"].update(size_bytes=True),
            "wrong resolved tool": lambda row: row["tools"]["cmake"].update(resolved_path="/wrong"),
            "empty alias": lambda row: row["tools"].update({"": row["tools"]["cmake"]}),
            "slash alias": lambda row: row["tools"].update({"bad/name": row["tools"]["cmake"]}),
            "backslash alias": lambda row: row["tools"].update({"bad\\name": row["tools"]["cmake"]}),
            "unknown CMake resolution": lambda row: row["cmake_selection"].update(resolution="other"),
            "missing native CMake": lambda row: row["cmake_selection"].pop("native"),
            "CMake selection wrong type": lambda row: row.update(cmake_selection=[]),
        }
        for index, (label, change) in enumerate(cases.items()):
            with self.subTest(case=label):
                receipt = deepcopy(original)
                change(receipt)
                self.write_receipt(path, receipt)
                output = self.base / ("invalid-" + str(index))
                code, summary, loader, _, _ = self.run_main(
                    lambda: self.fail("invalid receipt reached a body"), output=output,
                    receipt=path, interpreter=interpreter)
                self.assertEqual(code, 1)
                self.assertFalse(loader.calls)
                self.assertFalse(summary["governance_passed"])
                self.assertFalse(summary["execution_completed"])
                self.assertTrue(summary["errors"])
                self.assert_started_only(output)
                self.assertFalse(self.command_marker.exists())

    def test_malformed_duplicate_and_oversized_json_reject_before_discovery(self):
        path, receipt, interpreter = self.environment_fixture()
        valid = json.dumps(receipt)
        cases = {
            "malformed": b"{unfinished",
            "invalid utf8": b"\xff",
            "non-object": b"[]",
            "null": b"null",
            "duplicate root": valid.replace('"status": "ready"',
                                            '"status": "preparing", "status": "ready"').encode(),
            "duplicate nested": valid.replace('"PATH": ', '"PATH": "ignored", "PATH": ').encode(),
            "NaN": (valid[:-1] + ', "invalid_number": NaN}').encode(),
            "Infinity": (valid[:-1] + ', "invalid_number": Infinity}').encode(),
            "negative Infinity": (valid[:-1] + ', "invalid_number": -Infinity}').encode(),
            "oversized": b" " * (1024**2 + 1),
        }
        for index, (label, raw) in enumerate(cases.items()):
            with self.subTest(case=label):
                path.write_bytes(raw)
                output = self.base / ("malformed-" + str(index))
                code, summary, loader, _, _ = self.run_main(
                    lambda: self.fail("malformed receipt reached a body"), output=output,
                    receipt=path, interpreter=interpreter)
                self.assertEqual(code, 1)
                self.assertFalse(loader.calls)
                self.assertFalse(summary["governance_passed"])
                self.assertFalse(summary["execution_completed"])
                self.assertTrue(summary["errors"])
                if label.startswith("duplicate"):
                    self.assertIn("duplicate environment receipt key", summary["errors"][0]["message"])
                self.assertFalse(self.command_marker.exists())

    def test_missing_relative_and_nonexecutable_environment_inputs_reject(self):
        path, receipt, interpreter = self.environment_fixture()
        for index, candidate in enumerate((self.base / "missing.json", Path("environment.json"))):
            with self.subTest(path=str(candidate)):
                code, summary, loader, _, _ = self.run_main(
                    output=self.base / ("path-" + str(index)), receipt=candidate, interpreter=interpreter)
                self.assertEqual(code, 1)
                self.assertFalse(loader.calls)
                self.assertFalse(summary["governance_passed"])
        Path(receipt["tools"]["cmake"]["resolved_path"]).chmod(0o644)
        code, summary, loader, _, _ = self.run_main(receipt=path, interpreter=interpreter)
        self.assertEqual(code, 1)
        self.assertFalse(loader.calls)
        self.assertFalse(summary["governance_passed"])
        self.assertIn("tool identity changed", summary["errors"][0]["message"])


class GovernanceRunBlackboxTests(_Workspace):
    def prepare_runner(self, test_source):
        script = self.source / "ci/project/governance_run.py"
        shutil.copyfile(RUNNER_PATH, script)
        (self.source / "ci/project/test_probe.py").write_text(
            textwrap.dedent(test_source), encoding="utf-8")
        self.git("add", "ci/project")
        self.commit("bounded discovery fixture")
        return script

    def run_receipt_rejection(self, *receipt_arguments):
        script = self.prepare_runner("""
            from pathlib import Path
            import unittest

            markers = Path(__file__).resolve().parents[3]
            (markers / 'discovery-started').write_text('imported')

            class TinyProbe(unittest.TestCase):
                def test_body(self):
                    (markers / 'body-started').write_text('executed')
        """)
        completed = subprocess.run(
            [sys.executable, "-B", str(script), "--output-dir", str(self.output),
             *receipt_arguments],
            cwd=self.base, env=self.process_environment, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=20, check=False)
        self.assertFalse((self.base / "discovery-started").exists())
        self.assertFalse((self.base / "body-started").exists())
        self.assertNotIn("Strict governance PASSED", completed.stdout + completed.stderr)
        return completed

    def assert_incomplete_receipt_rejection(self, completed, error_type, error_message):
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        summary = self.read_json(self.output / "summary.json")
        self.assertEqual(summary["status"], "incomplete")
        self.assertFalse(summary["execution_completed"])
        self.assertFalse(summary["governance_passed"])
        self.assertNotIn("execution", summary)
        self.assertEqual(len(summary["errors"]), 1)
        self.assertEqual(summary["errors"][0]["type"], error_type)
        self.assertIn(error_message, summary["errors"][0]["message"])
        self.assertIn(error_message, completed.stderr)
        self.assertIn("Strict governance FAILED", completed.stdout)
        self.assert_started_only()
        self.assertEqual(set(path.name for path in self.output.iterdir()), {
            "started.json", "events.jsonl", "unittest.log", "summary.json"})
        self.assertEqual((self.output / "events.jsonl").read_bytes(), b"")
        self.assertEqual((self.output / "unittest.log").read_bytes(), b"")

    def test_real_cli_requires_environment_receipt_before_creating_output(self):
        completed = self.run_receipt_rejection()
        self.assertEqual(completed.returncode, 2)
        self.assertIn("error: the following arguments are required: --environment-receipt",
                      completed.stderr)
        self.assertNotIn("Strict governance", completed.stdout)
        self.assertFalse(self.output.exists())

    def test_real_cli_rejects_empty_environment_receipt_before_discovery(self):
        completed = self.run_receipt_rejection("--environment-receipt", "")
        self.assert_incomplete_receipt_rejection(
            completed, "ValueError", "environment receipt must be a bounded absolute regular file")

    def test_real_cli_rejects_empty_environment_receipt_file_before_discovery(self):
        path = self.base / "empty-environment.json"
        path.write_bytes(b"")
        completed = self.run_receipt_rejection("--environment-receipt", str(path))
        self.assert_incomplete_receipt_rejection(completed, "JSONDecodeError", "Expecting value")
        self.assertEqual(path.read_bytes(), b"")

    def test_real_cli_discovers_and_runs_only_the_tiny_committed_population(self):
        script = self.prepare_runner("""
            from pathlib import Path
            import unittest

            class TinyProbe(unittest.TestCase):
                def test_source(self):
                    self.assertEqual(Path('tracked.txt').read_text(), 'committed input\\n')
                    print('real CLI body executed')
        """)
        path, receipt, interpreter = self.environment_fixture(python_executable=sys.executable)
        environment = {**self.process_environment, **receipt["environment"]}
        completed = subprocess.run(
            [str(interpreter), "-B", str(script), "--output-dir", str(self.output),
             "--environment-receipt", str(path)],
            cwd=self.base, env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=20, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        summary = self.read_json(self.output / "summary.json")
        self.assertTrue(summary["governance_passed"])
        self.assertTrue(summary["execution_completed"])
        self.assertTrue(summary["environment_stable"])
        self.assertEqual(summary["environment_before"], summary["environment_after"])
        self.assertEqual(summary["environment_before"]["receipt_path"], str(path))
        self.assertEqual(summary["source_root"], str(self.source))
        self.assertEqual(summary["discovery"], {"start_directory": "ci/project", "pattern": "test_*.py"})
        self.assertEqual(self.read_json(self.output / "discovered.json")["test_ids"],
                         ["test_probe.TinyProbe.test_source"])
        self.assertEqual(summary["execution"]["outcome_counts"], {"success": 1})
        self.assertIn("real CLI body executed", (self.output / "unittest.log").read_text())
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assert_started_only()
        self.assertFalse(self.command_marker.exists())

    def test_real_cli_rejects_discovery_filters_before_creating_output(self):
        path, receipt, interpreter = self.environment_fixture(python_executable=sys.executable)
        environment = {**self.process_environment, **receipt["environment"]}
        for index, arguments in enumerate((
                ["--pattern", "test_probe.py"], ["--start-directory", "elsewhere"],
                ["--test-id", "test_probe.TinyProbe.test_source"])):
            with self.subTest(arguments=arguments):
                output = self.base / ("filter-" + str(index))
                completed = subprocess.run(
                    [str(interpreter), "-B", str(RUNNER_PATH), "--output-dir", str(output),
                     "--environment-receipt", str(path), *arguments],
                    cwd=self.base, env=environment, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True, timeout=10, check=False)
                self.assertEqual(completed.returncode, 2)
                self.assertIn("unrecognized arguments", completed.stderr)
                self.assertNotIn("the following arguments are required", completed.stderr)
                self.assertFalse(output.exists())
        self.assertFalse(self.command_marker.exists())

    def test_terminated_real_process_keeps_started_evidence_without_a_completed_pass(self):
        script = self.prepare_runner("""
            import os
            from pathlib import Path
            import time
            import unittest

            class TinyProbe(unittest.TestCase):
                def test_wait_for_termination(self):
                    output = Path(os.environ['GOVERNANCE_TEST_OUTPUT'])
                    (output / 'body-started').write_text('entered')
                    while True:
                        time.sleep(0.05)
        """)
        path, receipt, interpreter = self.environment_fixture(python_executable=sys.executable)
        environment = {**self.process_environment, **receipt["environment"],
                       "GOVERNANCE_TEST_OUTPUT": str(self.output)}
        with tempfile.TemporaryFile() as process_log:
            process = subprocess.Popen(
                [str(interpreter), "-B", str(script), "--output-dir", str(self.output),
                 "--environment-receipt", str(path)],
                cwd=self.base, env=environment, stdout=process_log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 10
                while not (self.output / "body-started").exists() and process.poll() is None \
                        and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue((self.output / "body-started").exists(), "child did not enter its body")
                started = self.assert_started_only()
                self.assertTrue(started["source_before"]["clean"])
                self.assertFalse((self.output / "summary.json").exists())
                process.terminate()
                self.assertNotEqual(process.wait(timeout=5), 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
        self.assert_started_only()
        self.assertFalse((self.output / "summary.json").exists())
        self.assertEqual(self.read_json(self.output / "discovered.json")["count"], 1)
        events = [json.loads(line) for line in (self.output / "events.jsonl").read_text().splitlines()]
        self.assertEqual([event["event"] for event in events], ["test_start"])
        self.assertEqual(events[0]["test_id"], "test_probe.TinyProbe.test_wait_for_termination")
        self.assertFalse(self.command_marker.exists())


if __name__ == "__main__":
    unittest.main()
