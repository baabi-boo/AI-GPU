# SPDX-License-Identifier: Apache-2.0
"""Exercise host-only replay CI identity, pinning and failure propagation."""

from contextlib import redirect_stdout
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
import unittest
from unittest import mock

from test_p05_ci_workflow import children, path_filters, scalars, script, steps, workflow
from test_p06_workspace_ci import covers


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/p06-managed-preflight-replay.yml"
NATIVE = "docs/project/evidence/p06-managed-preflight/native"
INITIALIZE = "Retain replay identity and verify pinned inputs"
REPLAY = "Replay the original successful archive"
FAILED = "Require the original failed archive to remain rejected"
TESTS = "Test the inert replay and source derivation"
REVISION = "57248e73dfce4ae2d21d2cbdb82c3953eef2e3db"
FAILED_REVISION = "8756f40029e59c87546fa22f4da33acd4e5d8e02"
PINS = {
    "run-45085300171-attempt1.zip": "cee5be4dba875494f6eafb83484933ab7693428e4773b932a26d5b91bd17969d",
    "source-inventory-57248e73.json": "72ca7e9237060ca2831a275811d27ec6fdb3507dfd9a00b693aa177aa68382e8",
    "source-derivation-57248e73.json": "3b25d30eceeee2dc5cebd1cce8ed7ab90da0fec64857e82fc7cc7fc3ca38e171",
    "run-45084009157-attempt1.zip": "4f1e177ba930c132f5e8cc7558b3087d39789c346763f00a9d1bdd2a6d17d00c",
    "source-inventory-8756f400-replay.json": "57a1290e4cadb7e357d109b49ff7e2ee85459c42b9a54d9522e1e178f3323c30",
    "source-derivation-8756f400-replay.json": "492b142b047e71a84a62425aebf5d46bb35f2ec022a173d42d6463e04fe834b8",
}
CLAIMS = ("qualified", "ready_for_warm", "warm_execution", "full_warm_coverage",
          "acceptance_claimed", "phase_acceptance", "performance_acceptance")
FAILED_RESULT = {
    "contract_id": "p06-managed-counter-preflight-replay-v1", "outcome": "fail",
    "reason": "report.outcome: value differs", "native_execution": "not_run",
    "retained_code_executed": False, "dependency_compilation_provenance_verified": False,
    **dict.fromkeys(CLAIMS, False),
}
PATTERNS = (
    "test_p06_managed_preflight_replay*.py", "test_p06_managed_preflight_source_export.py",
    "test_p06_managed_preflight_application_build.py", "test_p06_managed_preflight_derivation.py",
    "test_p06_managed_preflight_generated.py",
)


def expected_arguments(*, failed=False, root=ROOT):
    prefix = "8756f400" if failed else "57248e73"
    suffix = "-replay" if failed else ""
    archive = "run-45084009157-attempt1.zip" if failed else "run-45085300171-attempt1.zip"
    inventory = "source-inventory-" + prefix + suffix + ".json"
    derivation = "source-derivation-" + prefix + suffix + ".json"
    return ["ci/project/p06_managed_preflight_replay.py", "--archive", str(root / NATIVE / archive),
        "--sha256", PINS[archive], "--source-revision", FAILED_REVISION if failed else REVISION,
        "--source-inventory", str(root / NATIVE / inventory), "--source-inventory-sha256", PINS[inventory],
        "--source-derivation", str(root / NATIVE / derivation), "--source-derivation-sha256", PINS[derivation]]


def environment(root):
    return {
        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
        "PYTHONDONTWRITEBYTECODE": "1", "RUNNER_TEMP": str(root),
        "GITHUB_ENV": str(root / "github-env"), "GITHUB_SHA": "1" * 40,
        "GITHUB_EVENT_NAME": "pull_request", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_JOB": "replay", "GITHUB_REPOSITORY": "host-only/synthetic", "GITHUB_REF": "refs/pull/7/merge",
    }


class ManagedPreflightReplayWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = workflow(WORKFLOW)
        cls.events = children(cls.workflow, "on", 2)
        cls.jobs = children(cls.workflow, "jobs", 2)
        cls.job = children(cls.jobs, "replay", 4)
        cls.steps = steps(cls.job)

    def one(self, key, value):
        found = [step for step in self.steps if step.get(key, (None,))[0] == value]
        self.assertEqual(len(found), 1, (key, value))
        return found[0]

    def python_body(self, name):
        lines = script(self.one("name", name)).splitlines()
        self.assertEqual(lines[0], "set -euo pipefail")
        self.assertRegex(lines[1], r"^python3(?: -I)? - <<'PY'(?: 2>&1 \| tee .*)?$")
        self.assertEqual(lines[-1], "PY")
        return "\n".join(lines[2:-1])

    def test_read_only_events_checkout_and_hosted_runner_are_closed(self):
        self.assertEqual(set(self.workflow), {"name", "on", "permissions", "concurrency", "jobs"})
        self.assertEqual(set(self.events), {"push", "pull_request", "workflow_dispatch"})
        self.assertEqual(self.events["workflow_dispatch"], ("", []))
        self.assertEqual(children(self.events, "push", 4)["branches"], ("[master]", []))
        self.assertEqual(set(children(self.events, "push", 4)), {"branches", "paths"})
        self.assertEqual(set(children(self.events, "pull_request", 4)), {"paths"})
        self.assertEqual(scalars(children(self.workflow, "permissions", 2)), {"contents": "read"})
        self.assertEqual(scalars(children(self.workflow, "concurrency", 2)), {
            "group": "p06-managed-preflight-replay-${{ github.event_name }}-${{ github.ref }}",
            "cancel-in-progress": "false",
        })
        self.assertEqual(set(self.jobs), {"replay"})
        self.assertEqual(self.job["runs-on"], ("ubuntu-24.04", []))
        self.assertEqual(self.job["timeout-minutes"], ("20", []))
        self.assertEqual(scalars(children(self.one("uses", "actions/checkout@v4"), "with", 10)), {
            "fetch-depth": "1", "submodules": "false", "lfs": "false", "persist-credentials": "false",
        })
        self.assertEqual([row["uses"][0] for row in self.steps if "uses" in row], [
            "actions/checkout@v4", "actions/upload-artifact@v4",
        ])
        self.assertNotRegex(WORKFLOW.read_text(),
            r"secrets\s*\.|pull_request_target|workflow_run|self-hosted|write-all|id-token:|continue-on-error")

    def test_triggers_cover_reader_inputs_and_frozen_external_expectations(self):
        names = {WORKFLOW.relative_to(ROOT).as_posix(), ".github/workflows/project-governance.yml",
            "docs/project/evidence/p05-torch/reviews/archive_reader.py",
            "docs/project/evidence/p06-managed-preflight-replay/README.md",
            "docs/designs/managed_counter_preflight_replay_v1.md", "LICENSE"}
        names.update(str(Path(NATIVE) / name) for name in PINS)
        names.update(path.relative_to(ROOT).as_posix() for path in (ROOT / "ci/project").glob("*.py"))
        warm = json.loads((ROOT / "ci/project/p06_warm_contract.json").read_text())
        names.update(row["path"] for row in warm["source_inputs"])
        self.assertEqual(path_filters(self.events, "push"), path_filters(self.events, "pull_request"))
        for event in ("push", "pull_request"):
            patterns = path_filters(self.events, event)
            self.assertEqual(sorted(name for name in names if not covers(patterns, name)), [], event)
            for pattern, witness in (
                ("ci/project/**", "ci/project/p06_managed_preflight_replay.py"),
                ("ci/gen_config.py", "ci/gen_config.py"),
                ("docs/project/evidence/p06-managed-preflight/**", str(Path(NATIVE) / next(iter(PINS)))),
                ("docs/project/evidence/p05-torch/reviews/archive_reader.py",
                 "docs/project/evidence/p05-torch/reviews/archive_reader.py"),
            ):
                self.assertFalse(covers(patterns - {pattern}, witness), (event, witness))

    def test_new_workflow_and_contract_trigger_full_governance(self):
        governance = workflow(ROOT / ".github/workflows/project-governance.yml")
        events = children(governance, "on", 2)
        for event in ("push", "pull_request"):
            patterns = path_filters(events, event)
            for name in (WORKFLOW.relative_to(ROOT).as_posix(),
                         "docs/designs/managed_counter_preflight_replay_v1.md"):
                self.assertTrue(covers(patterns, name), (event, name))
        job = children(children(governance, "jobs", 2), "governance", 4)
        self.assertEqual(job["timeout-minutes"], ("60", []))

    def test_job_cannot_install_or_execute_native_payloads_or_suppress_failure(self):
        self.assertEqual(set(self.job), {"name", "runs-on", "timeout-minutes", "defaults", "env", "steps"})
        self.assertEqual(scalars(children(self.job, "env", 6)), {"PYTHONDONTWRITEBYTECODE": "'1'"})
        self.assertEqual(scalars(children(children(self.job, "defaults", 6), "run", 8)), {"shell": "bash"})
        for step in self.steps:
            self.assertTrue(set(step) <= {"name", "uses", "with", "run", "if"})
            if "if" in step:
                self.assertIs(step, self.one("uses", "actions/upload-artifact@v4"))
            if "run" in step:
                self.assertNotRegex(script(step), r"\|\|\s*true|set\s+\+|(?:^|\s)exit\s+0|"
                    r"p06_managed_preflight_execute|p04_ci_prepare|toolchain_install|install_dependencies|"
                    r"(?:curl|wget|make|sudo|git clone|unzip|tar)\s")
        self.assertEqual([step.get("name", (None,))[0] for step in self.steps], [
            None, INITIALIZE, REPLAY, FAILED, TESTS, "Preserve replay identity, results and failure logs",
        ])

    def test_successful_replay_command_requires_independent_original_pins(self):
        lines = script(self.one("name", REPLAY)).replace("\\\n", " ").splitlines()
        self.assertEqual(lines[0], "set -euo pipefail")
        self.assertEqual(len(lines), 2)
        expected = ["python3", *expected_arguments(root=Path("$PWD")),
            "--output", "$P06_MANAGED_REPLAY_ROOT/evidence/replay.json", "2>&1", "|", "tee",
            "$P06_MANAGED_REPLAY_ROOT/evidence/replay.log"]
        self.assertEqual(shlex.split(lines[1]), expected)
        self.assertNotIn("$GITHUB_SHA", lines[1])

    def test_initial_identity_retains_all_pins_python_and_false_claims(self):
        with tempfile.TemporaryDirectory(prefix="p06-managed-replay-ci-") as temporary:
            root = Path(temporary)
            env = environment(root)
            result = subprocess.run([sys.executable, "-I", "-"], input=self.python_body(INITIALIZE),
                cwd=ROOT, env=env, capture_output=True, text=True, timeout=15)
            expected_python = sys.version_info[:2] == (3, 12) and sys.implementation.name == "cpython" and sys.platform == "linux"
            self.assertEqual(result.returncode, 0 if expected_python else 1, result.stderr)
            evidence = root / "p06-managed-preflight-replay/evidence"
            data = json.loads((evidence / "job.json").read_text())
            self.assertEqual(data["GITHUB_SHA"], env["GITHUB_SHA"])
            self.assertNotEqual(data["GITHUB_SHA"], data["original_source_revision"])
            self.assertEqual((data["original_source_revision"], data["failed_source_revision"]), (REVISION, FAILED_REVISION))
            self.assertEqual(data["native_execution"], "not_run")
            for field in (*CLAIMS, "retained_code_executed", "dependency_compilation_provenance_verified"):
                self.assertIs(data[field], False)
            self.assertEqual(data["python_version"], list(sys.version_info[:3]))
            self.assertEqual(data["executable"], sys.executable)
            self.assertEqual(data["workflow_sha256"], hashlib.sha256(WORKFLOW.read_bytes()).hexdigest())
            self.assertEqual((evidence / "workflow.yml").read_bytes(), WORKFLOW.read_bytes())
            self.assertEqual({Path(row["path"]).name: row["sha256"] for row in data["inputs"]}, PINS)
            self.assertTrue(all(row["expected_sha256"] == row["sha256"] and row["size_bytes"] > 0
                                and row["error"] is None for row in data["inputs"]))
            self.assertEqual((root / "github-env").read_text(),
                             "P06_MANAGED_REPLAY_ROOT=" + str(evidence.parent) + "\n")
            before = {path.name: path.read_bytes() for path in evidence.iterdir()}
            repeated = subprocess.run([sys.executable, "-I", "-"], input=self.python_body(INITIALIZE),
                cwd=ROOT, env=env, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertEqual({path.name: path.read_bytes() for path in evidence.iterdir()}, before)

    def test_missing_or_changed_input_fails_after_retaining_identity(self):
        for damage in ("missing", "changed"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory(prefix="p06-replay-ci-pin-") as temporary:
                root = Path(temporary)
                workspace, runner = root / "workspace", root / "runner"
                (workspace / NATIVE).mkdir(parents=True)
                (workspace / WORKFLOW.relative_to(ROOT)).parent.mkdir(parents=True)
                (workspace / WORKFLOW.relative_to(ROOT)).write_bytes(WORKFLOW.read_bytes())
                runner.mkdir()
                target = next(iter(PINS))
                for name in PINS:
                    destination = workspace / NATIVE / name
                    if name == target:
                        if damage == "changed":
                            destination.write_bytes(b"changed input, never executed")
                    else:
                        shutil.copyfile(ROOT / NATIVE / name, destination)
                result = subprocess.run([sys.executable, "-I", "-"], input=self.python_body(INITIALIZE),
                    cwd=workspace, env=environment(runner), capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 1)
                self.assertIn("Historical replay inputs differ", result.stderr)
                evidence = runner / "p06-managed-preflight-replay/evidence"
                data = json.loads((evidence / "job.json").read_text())
                changed = next(row for row in data["inputs"] if Path(row["path"]).name == target)
                self.assertNotEqual(changed["sha256"], changed["expected_sha256"])
                self.assertEqual(changed["error"] is None, damage == "changed")
                self.assertTrue((evidence / "workflow.yml").is_file())

    def test_wrong_python_version_is_a_recorded_failure(self):
        with tempfile.TemporaryDirectory(prefix="p06-replay-ci-version-") as temporary:
            root = Path(temporary)
            body = "import sys\nsys.version_info = (3, 11, 0)\n" + self.python_body(INITIALIZE)
            result = subprocess.run([sys.executable, "-I", "-"], input=body,
                cwd=ROOT, env=environment(root), capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 1)
            self.assertIn("system CPython 3.12", result.stderr)
            data = json.loads((root / "p06-managed-preflight-replay/evidence/job.json").read_text())
            self.assertEqual(data["python_version"], [3, 11, 0])

    def failed_control(self, root, *, returncode=1, data=FAILED_RESULT, stdout=None, stderr=""):
        body = self.python_body(FAILED)
        result = subprocess.CompletedProcess([], returncode, json.dumps(data) if stdout is None else stdout, stderr)
        with mock.patch.dict(os.environ, {"P06_MANAGED_REPLAY_ROOT": str(root)}), \
             mock.patch.object(subprocess, "run", return_value=result) as called, redirect_stdout(io.StringIO()):
            exec(compile(body, "<current-failed-control>", "exec"), {})
        self.assertEqual(called.call_args.args[0], [sys.executable, *expected_arguments(failed=True)])
        self.assertEqual(called.call_args.kwargs, {"text": True, "capture_output": True, "timeout": 120})

    def test_failed_original_harness_accepts_only_its_semantic_rejection(self):
        with tempfile.TemporaryDirectory(prefix="p06-replay-ci-rejection-") as temporary:
            root = Path(temporary)
            (root / "evidence").mkdir()
            self.failed_control(root)
            data = json.loads((root / "evidence/failed-control.json").read_text())
            self.assertEqual(data["outcome"], "pass")
            self.assertEqual(data["replay_exit_code"], 1)
            self.assertEqual(data["replay"], FAILED_RESULT)
            self.assertIs(data["acceptance_claimed"], False)
            self.assertEqual((root / "evidence/failed-original.stderr").read_text(), "")

    def test_failed_original_harness_rejects_incidental_and_claimed_successes(self):
        cases = [
            {"returncode": 0}, {"returncode": 2}, {"stderr": "missing script"}, {"stdout": ""},
            {"stdout": "usage: invalid options\n"}, {"data": dict(FAILED_RESULT, reason="unrelated failure")},
            {"data": dict(FAILED_RESULT, qualified=True)}, {"data": dict(FAILED_RESULT, qualified=0)},
            {"data": dict(FAILED_RESULT, native_execution="run")},
            {"data": dict(FAILED_RESULT, unexpected=False)},
            {"stdout": json.dumps(FAILED_RESULT)[:-1] + ', "outcome": "fail"}'},
        ]
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory(prefix="p06-replay-ci-reject-") as temporary:
                root = Path(temporary)
                (root / "evidence").mkdir()
                with self.assertRaises((SystemExit, ValueError)):
                    self.failed_control(root, **case)
                self.assertFalse((root / "evidence/failed-control.json").exists())
                self.assertTrue((root / "evidence/failed-original.stdout").exists())
                self.assertTrue((root / "evidence/failed-original.stderr").exists())

    def test_actual_shell_pipelines_retain_both_streams_and_propagate_failure(self):
        for name, log in ((REPLAY, "replay.log"), (FAILED, "failed-control.log"), (TESTS, "tests.log")):
            for code in (0, 7):
                with self.subTest(step=name, code=code), tempfile.TemporaryDirectory(prefix="p06-replay-ci-pipe-") as temporary:
                    root = Path(temporary)
                    (root / "evidence").mkdir()
                    (root / "bin").mkdir()
                    standin = root / "bin/python3"
                    standin.write_text("#!/bin/sh\nprintf '%s\\n' synthetic-stdout\n"
                        "printf '%s\\n' synthetic-stderr >&2\nexit " + str(code) + "\n")
                    standin.chmod(0o700)
                    env = {"PATH": str(root / "bin") + os.pathsep + os.defpath, "P06_MANAGED_REPLAY_ROOT": str(root)}
                    result = subprocess.run(["bash", "-e", "-c", script(self.one("name", name))],
                        cwd=ROOT, env=env, capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, code, result.stderr)
                    self.assertEqual((root / "evidence" / log).read_text(), "synthetic-stdout\nsynthetic-stderr\n")

    def test_all_focused_test_groups_are_required_and_failure_reaches_exit(self):
        for success in (True, False):
            with self.subTest(success=success):
                loader = mock.Mock()
                loader.discover.side_effect = lambda *args, **kwargs: unittest.TestSuite([
                    unittest.FunctionTestCase(lambda: None)])
                result = mock.Mock()
                result.wasSuccessful.return_value = success
                with mock.patch.object(unittest, "TestLoader", return_value=loader), \
                     mock.patch.object(unittest, "TextTestRunner") as runner:
                    runner.return_value.run.return_value = result
                    with self.assertRaises(SystemExit) as caught:
                        exec(compile(self.python_body(TESTS), "<current-test-selection>", "exec"), {})
                self.assertEqual(caught.exception.code, 0 if success else 1)
                self.assertEqual(loader.discover.call_args_list, [
                    mock.call("ci/project", pattern=pattern) for pattern in PATTERNS])
                self.assertEqual(runner.call_args, mock.call(verbosity=2))
                self.assertEqual(runner.return_value.run.call_args.args[0].countTestCases(), len(PATTERNS))

    def test_empty_required_test_group_cannot_pass(self):
        loader = mock.Mock()
        loader.discover.return_value = unittest.TestSuite()
        with mock.patch.object(unittest, "TestLoader", return_value=loader), \
             mock.patch.object(unittest, "TextTestRunner") as runner:
            with self.assertRaisesRegex(RuntimeError, "Required replay test group is missing"):
                exec(compile(self.python_body(TESTS), "<current-test-selection>", "exec"), {})
        runner.assert_not_called()

    def test_artifact_upload_preserves_results_on_failure_with_unique_identity(self):
        upload = self.one("uses", "actions/upload-artifact@v4")
        self.assertEqual(set(upload), {"name", "if", "uses", "with"})
        self.assertEqual(upload["if"], ("always()", []))
        self.assertEqual(scalars(children(upload, "with", 10)), {
            "name": "p06-managed-preflight-replay-${{ github.sha }}-run${{ github.run_id }}-attempt${{ github.run_attempt }}",
            "path": "${{ runner.temp }}/p06-managed-preflight-replay/evidence", "if-no-files-found": "error",
            "retention-days": "30", "compression-level": "6", "include-hidden-files": "true",
        })
        self.assertIs(self.steps[-1], upload)

    def test_every_current_shell_and_python_block_is_syntax_valid(self):
        for step in self.steps:
            if "run" in step:
                with self.subTest(step=step.get("name")):
                    result = subprocess.run(["bash", "-n"], input=script(step), text=True,
                        capture_output=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
        for name in (INITIALIZE, FAILED, TESTS):
            compile(self.python_body(name), "<current-workflow-python>", "exec")


if __name__ == "__main__":
    unittest.main()
