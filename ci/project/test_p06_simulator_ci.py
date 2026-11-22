# SPDX-License-Identifier: Apache-2.0
"""Host-only completion CI trust, execution bounds and retained failure checks."""

from contextlib import redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from baseline_inventory import SOURCE_INPUTS
import p04_ci_prepare
import p06_simulator_execute as runner
from test_p05_ci_workflow import children, path_filters, scalars, script, steps, workflow
from test_p06_workspace_ci import covers, heredoc_body, one_command


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/p06-simulator-completion.yml"
PREPARE = "Verify clean source and relocate restored tools"
EXECUTE = "Execute checked model and public runtime controls"
IDENTITY = "Initialize retained job identity"
PYTHON_IDENTITY = "Retain and verify Python interpreter identity"


def required_sources():
    names = set(SOURCE_INPUTS + runner.SOURCE_FILES + runner.base.COPIED
                + runner.base.TOOLING + runner.base.CORPUS)
    names.update(row["path"] for row in runner.LOADED_HELPERS)
    for directory in runner.base.SOURCE_ROOTS:
        names.update(path.relative_to(ROOT).as_posix()
                     for path in (ROOT / directory).rglob("*")
                     if path.is_file() and (path.suffix in runner.base.SOURCE_SUFFIXES
                                            or path.name == "Makefile"))
    names.update({"Makefile.in", "profiles/p02-tfr.json", "third_party/Makefile",
                  ".github/workflows/p04-model.yml", "ci/toolchain_rev.sh",
                  "ci/install_dependencies.sh", Path(__file__).relative_to(ROOT).as_posix()})
    return names


class SimulatorCompletionWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = workflow(WORKFLOW)
        cls.events = children(cls.workflow, "on", 2)
        cls.jobs = children(cls.workflow, "jobs", 2)
        cls.job = children(cls.jobs, "completion", 4)
        cls.steps = steps(cls.job)

    def one(self, key, value):
        found = [step for step in self.steps if step.get(key, (None,))[0] == value]
        self.assertEqual(len(found), 1, (key, value))
        return found[0]

    def test_only_master_push_pull_request_and_untuned_manual_dispatch(self):
        self.assertEqual(set(self.workflow), {"name", "on", "permissions", "concurrency", "jobs"})
        self.assertEqual(set(self.events), {"push", "pull_request", "workflow_dispatch"})
        self.assertEqual(self.events["workflow_dispatch"], ("", []))
        self.assertEqual(children(self.events, "push", 4)["branches"], ("[master]", []))
        self.assertEqual(set(children(self.events, "push", 4)), {"branches", "paths"})
        self.assertEqual(set(children(self.events, "pull_request", 4)), {"paths"})
        self.assertEqual(path_filters(self.events, "push"), path_filters(self.events, "pull_request"))

    def test_native_retained_and_preparation_inputs_trigger_both_events(self):
        names = required_sources()
        for event in ("push", "pull_request"):
            patterns = path_filters(self.events, event)
            self.assertEqual(sorted(name for name in names if not covers(patterns, name)), [],
                             event + " omits retained or native build inputs")
            self.assertEqual(sorted(pattern for pattern in patterns
                                    if not any(covers({pattern}, name) for name in names)), [],
                             event + " includes unrelated inherited workflow paths")

    def test_missing_completion_or_preparation_paths_are_detectable(self):
        patterns = path_filters(self.events, "push")
        witnesses = {
            ".github/workflows/p04-model.yml": ".github/workflows/p04-model.yml",
            "ci/project/**": "ci/project/p06_simulator_execute.py",
            "sim/**": "sim/simx/completion.mk",
            "sw/**": "sw/runtime/common/async_run.h",
            "tests/unittest/simx_completion/**": "tests/unittest/simx_completion/main.cpp",
            "tests/regression/simx_completion/**": "tests/regression/simx_completion/kernel.cpp",
            "tests/regression/sgemm_tcu/**": "tests/regression/sgemm_tcu/p02_fixtures.h",
            "third_party/**": "third_party/Makefile",
            "docs/designs/simulator_completion_v1.md": "docs/designs/simulator_completion_v1.md",
        }
        for pattern, name in witnesses.items():
            with self.subTest(path=name):
                self.assertIn(name, required_sources())
                self.assertTrue(covers(patterns, name))
                self.assertFalse(covers(patterns - {pattern}, name))

    def test_one_hosted_serial_job_preserves_the_native_resource_bounds(self):
        self.assertEqual(set(self.jobs), {"completion"})
        self.assertEqual(set(self.job), {"name", "runs-on", "timeout-minutes", "defaults", "env", "steps"})
        self.assertEqual(self.job["runs-on"], ("ubuntu-22.04", []))
        self.assertEqual(self.job["timeout-minutes"], ("90", []))
        defaults = children(self.job, "defaults", 6)
        self.assertEqual(set(defaults), {"run"})
        self.assertEqual(scalars(children(defaults, "run", 8)), {"shell": "bash"})
        self.assertEqual(scalars(children(self.job, "env", 6)), {
            "P06_COMPLETION_BACKEND": "simx", "P06_COMPLETION_FORMAT": "fp16",
            "PYTHONDONTWRITEBYTECODE": "'1'", "MAKEFLAGS": "'-j2'", "THREADS": "'1'",
            "CMAKE_BUILD_PARALLEL_LEVEL": "'2'", "CCACHE_DISABLE": "'1'", "OBJCACHE": "''",
        })
        self.assertEqual(runner.BUDGET, {"min_free_bytes": 15 * 1024**3,
                                      "max_rss_bytes": 4 * 1024**3, "max_log_bytes": 16 * 1024**2})
        self.assertEqual(runner.TIMEOUTS, {"configure": 120, "build": 1800, "run": 180, "probe": 30})
        self.assertEqual((p04_ci_prepare.MIN_FREE_BYTES, p04_ci_prepare.MAX_RSS_BYTES),
                         (15 * 1024**3, 4 * 1024**3))
        self.assertNotRegex(WORKFLOW.read_text(), r"matrix\.|max-parallel|strategy:")

    def test_read_only_hosted_trust_cannot_suppress_failures_or_write_caches(self):
        self.assertEqual(scalars(children(self.workflow, "permissions", 2)), {"contents": "read"})
        self.assertEqual(scalars(children(self.workflow, "concurrency", 2)), {
            "group": "p06-simulator-completion-${{ github.event_name }}-${{ github.ref }}",
            "cancel-in-progress": "false"})
        checkout = self.one("uses", "actions/checkout@v4")
        self.assertEqual(set(checkout), {"uses", "with"})
        self.assertEqual(scalars(children(checkout, "with", 10)), {
            "fetch-depth": "1", "submodules": "recursive", "persist-credentials": "false"})
        self.assertEqual([step["uses"][0] for step in self.steps if "uses" in step], [
            "actions/checkout@v4", "actions/setup-python@v5", "actions/cache/restore@v4",
            "actions/cache/restore@v4", "actions/upload-artifact@v4"])
        for step in self.steps:
            self.assertTrue(set(step) <= {"name", "uses", "with", "run", "id", "if", "env", "timeout-minutes"})
            if "if" in step:
                self.assertIn(step, [self.one("name", "Install baseline host dependencies"),
                                     self.one("uses", "actions/upload-artifact@v4")])
            if "run" in step:
                self.assertNotRegex(script(step), r"\|\|\s*true|set\s+\+|(?:^|\s)exit\s+0|git\s+push|gh\s+")
        self.assertNotRegex(WORKFLOW.read_text(),
            r"secrets\s*(?:\.|\[)|pull_request_target|workflow_run|self-hosted|write-all|id-token:|contents:\s*write|continue-on-error")

    def test_pinned_cache_restore_is_read_only_and_precedes_clean_preparation(self):
        self.assertEqual(scalars(children(self.one("id", "toolchain"), "with", 10)), {
            "path": "tools", "key": "${{ runner.os }}-toolchain-${{ steps.pins.outputs.toolchain }}-lite",
            "restore-keys": "${{ runner.os }}-toolchain-${{ steps.pins.outputs.toolchain }}-"})
        self.assertEqual(scalars(children(self.one("id", "dependencies"), "with", 10)), {
            "path": "third_party", "key": "${{ runner.os }}-thirdparty-${{ hashFiles('third_party/Makefile', '.gitmodules') }}"})
        self.assertEqual(script(self.one("id", "pins")).splitlines(), [
            "set -euo pipefail", "P06_COMPLETION_TOOLCHAIN_ID=$(bash ci/toolchain_rev.sh)",
            '[[ "$P06_COMPLETION_TOOLCHAIN_ID" =~ ^[A-Za-z0-9._-]+-[0-9a-f]{40}$ ]]',
            'echo "toolchain=$P06_COMPLETION_TOOLCHAIN_ID" >> "$GITHUB_OUTPUT"'])
        install = self.one("name", "Install baseline host dependencies")
        self.assertEqual(install["if"], (
            "steps.toolchain.outputs.cache-matched-key != '' && steps.dependencies.outputs.cache-matched-key != ''", []))
        self.assertEqual(install["timeout-minutes"], ("15", []))
        self.assertEqual(one_command(install, pipefail=True), ["sudo", "bash", "ci/install_dependencies.sh",
            "2>&1", "|", "tee", "$P06_COMPLETION_ROOT/evidence/host-dependencies.log"])
        for step in self.steps:
            if "run" in step:
                self.assertNotRegex(script(step), r"toolchain_install|(?:curl|wget)\s|make\s.*third_party|git clone")
        order = [self.one("uses", "actions/checkout@v4"), self.one("name", IDENTITY),
                 self.one("uses", "actions/setup-python@v5"), self.one("name", PYTHON_IDENTITY),
                 self.one("id", "pins"), self.one("id", "toolchain"), self.one("id", "dependencies"),
                 install, self.one("name", PREPARE), self.one("name", EXECUTE),
                 self.one("uses", "actions/upload-artifact@v4")]
        self.assertEqual(self.steps, order)

    def test_existing_preparation_binds_source_revision_and_restored_cache_receipts(self):
        prepare = self.one("name", PREPARE)
        self.assertEqual(set(prepare), {"name", "env", "run"})
        self.assertEqual(scalars(children(prepare, "env", 10)), {
            "P06_COMPLETION_TOOLCHAIN_ID": "${{ steps.pins.outputs.toolchain }}",
            "P06_COMPLETION_TOOLCHAIN_CACHE": "${{ steps.toolchain.outputs.cache-matched-key }}",
            "P06_COMPLETION_DEPENDENCY_CACHE": "${{ steps.dependencies.outputs.cache-matched-key }}",
            "P06_COMPLETION_DEPENDENCY_KEY": "${{ runner.os }}-thirdparty-${{ hashFiles('third_party/Makefile', '.gitmodules') }}"})
        self.assertEqual(one_command(prepare, pipefail=True), [
            "python3", "ci/project/p04_ci_prepare.py", "--source-dir", "$PWD", "--workspace-dir", "$P06_COMPLETION_ROOT",
            "--expected-revision", "$GITHUB_SHA", "--toolchain-id", "$P06_COMPLETION_TOOLCHAIN_ID",
            "--toolchain-cache-key", "$P06_COMPLETION_TOOLCHAIN_CACHE", "--third-party-cache-key", "$P06_COMPLETION_DEPENDENCY_CACHE",
            "--expected-third-party-key", "$P06_COMPLETION_DEPENDENCY_KEY", "--backend", "$P06_COMPLETION_BACKEND",
            "--format", "$P06_COMPLETION_FORMAT", "2>&1", "|", "tee", "$P06_COMPLETION_ROOT/evidence/preparation.log"])

    def test_native_command_matches_the_actual_fixed_runner_cli(self):
        execute = self.one("name", EXECUTE)
        self.assertEqual(set(execute), {"name", "run"})
        command = one_command(execute, pipefail=True)
        self.assertEqual(command, [
            "python3", "ci/project/p06_simulator_execute.py", "--source-dir", "$PWD",
            "--tools-dir", "$P06_COMPLETION_ROOT/tools", "--work-dir", "$P06_COMPLETION_ROOT/work",
            "--output", "$P06_COMPLETION_ROOT/evidence/simulator-completion",
            "2>&1", "|", "tee", "$P06_COMPLETION_ROOT/evidence/execution.log"])
        parser = runner.argument_parser()
        options = {option for action in parser._actions for option in action.option_strings}
        self.assertEqual(options, {"-h", "--help", "--source-dir", "--tools-dir", "--work-dir", "--output", "--host-bin"})
        arguments = command[2:command.index("2>&1")]
        parsed = parser.parse_args(arguments)
        self.assertEqual((parsed.source_dir, parsed.tools_dir, parsed.work_dir, parsed.output),
                         tuple(Path(value) for value in arguments[1::2]))
        self.assertIsNone(parsed.host_bin)
        for option in ("--backend", "--format", "--case", "--development", "--jobs", "--threads",
                       "--timeout-seconds", "--run-timeout-seconds", "--min-free-gib", "--max-rss-bytes",
                       "--threshold", "--skip-unit", "--skip-public"):
            with self.subTest(option=option), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                parser.parse_args([*arguments, option, "1"])
            self.assertEqual(error.exception.code, 2)

    def test_failed_producers_retain_both_streams_and_fail_the_actual_pipelines(self):
        cases = (("Install baseline host dependencies", "host-dependencies.log", "sudo", "bash"),
                 (PREPARE, "preparation.log", "python3", "ci/project/p04_ci_prepare.py"),
                 (EXECUTE, "execution.log", "python3", "ci/project/p06_simulator_execute.py"))
        for label, log_name, program, first_argument in cases:
            with self.subTest(step=label), tempfile.TemporaryDirectory(prefix="completion-ci-pipeline-") as temporary:
                root = Path(temporary)
                (root / "evidence").mkdir()
                stub = root / program
                stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$P06_CI_ARGUMENTS"\n'
                                'printf "synthetic producer failed\\n"\n'
                                'printf "synthetic stderr\\n" >&2\nexit 37\n')
                stub.chmod(0o700)
                env = {"PATH": str(root) + os.pathsep + os.defpath, "P06_COMPLETION_ROOT": str(root),
                       "P06_CI_ARGUMENTS": str(root / "arguments"), "GITHUB_SHA": "1" * 40,
                       "P06_COMPLETION_BACKEND": "simx", "P06_COMPLETION_FORMAT": "fp16",
                       **{name: "synthetic-unused" for name in ("P06_COMPLETION_TOOLCHAIN_ID", "P06_COMPLETION_TOOLCHAIN_CACHE",
                            "P06_COMPLETION_DEPENDENCY_CACHE", "P06_COMPLETION_DEPENDENCY_KEY")}}
                result = subprocess.run(["/bin/bash", "-c", script(self.one("name", label))],
                    cwd=ROOT, env=env, text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 37, result.stderr)
                self.assertEqual((root / "evidence" / log_name).read_text(),
                                 "synthetic producer failed\nsynthetic stderr\n")
                self.assertEqual((root / "arguments").read_text().splitlines()[0], first_argument)

    def test_always_upload_includes_job_source_and_native_logs_with_attempt_identity(self):
        upload = self.one("uses", "actions/upload-artifact@v4")
        self.assertEqual(set(upload), {"name", "if", "uses", "with"})
        self.assertEqual(upload["if"], ("always()", []))
        self.assertEqual(scalars(children(upload, "with", 10)), {
            "name": "p06-simulator-completion-${{ github.sha }}-run${{ github.run_id }}-attempt${{ github.run_attempt }}",
            "path": "${{ runner.temp }}/p06-simulator-completion/evidence", "if-no-files-found": "error",
            "retention-days": "30", "compression-level": "6", "include-hidden-files": "true"})
        self.assertEqual(self.steps[-1], upload)

    def test_actual_job_initialization_is_retained_before_execution_and_cannot_be_reused(self):
        body = heredoc_body(self.one("name", IDENTITY), "python3 - <<'PY'")
        with tempfile.TemporaryDirectory(prefix="completion-ci-identity-") as temporary:
            root = Path(temporary)
            env = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
                   "RUNNER_TEMP": str(root), "GITHUB_ENV": str(root / "github-env"),
                   "GITHUB_SHA": "1" * 40, "GITHUB_EVENT_NAME": "pull_request", "GITHUB_RUN_ID": "123",
                   "GITHUB_RUN_ATTEMPT": "2", "GITHUB_JOB": "completion", "GITHUB_REPOSITORY": "host-test/synthetic",
                   "GITHUB_REF": "refs/pull/1/merge", "P06_COMPLETION_BACKEND": "simx", "P06_COMPLETION_FORMAT": "fp16"}
            result = subprocess.run([sys.executable, "-I", "-"], input=body, cwd=ROOT, env=env,
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = root / "p06-simulator-completion/evidence"
            self.assertEqual((evidence / "workflow.yml").read_bytes(), WORKFLOW.read_bytes())
            data = json.loads((evidence / "job.json").read_text())
            expected = {key: value for key, value in env.items() if key.startswith(("GITHUB_", "P06_COMPLETION_"))
                        and key != "GITHUB_ENV"}
            self.assertEqual(data, dict(expected, scope="simulator-completion-prerequisite",
                record_stage="job-initialization", native_execution="not_run", acceptance_claimed=False,
                workflow_sha256=hashlib.sha256(WORKFLOW.read_bytes()).hexdigest()))
            self.assertEqual((root / "github-env").read_text(),
                             "P06_COMPLETION_ROOT=" + str(root / "p06-simulator-completion") + "\n")
            repeated = subprocess.run([sys.executable, "-I", "-"], input=body, cwd=ROOT, env=env,
                                      text=True, capture_output=True, timeout=10)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertEqual(json.loads((evidence / "job.json").read_text()), data)

    def test_python_pin_checks_and_retains_the_executing_interpreter(self):
        self.assertEqual(scalars(children(self.one("uses", "actions/setup-python@v5"), "with", 10)), {
            "python-version": "'3.12.14'", "architecture": "x64", "check-latest": "false"})
        body = heredoc_body(self.one("name", PYTHON_IDENTITY), "python3 -I - <<'PY'")
        for token in ("data['python_version'] != [3, 12, 14]", "data['implementation'] != 'CPython'",
                      "data['platform'] != 'linux'", "Path(data['python3_on_path']).resolve() != Path(sys.executable).resolve()",
                      "raise SystemExit("):
            self.assertIn(token, body)
        with tempfile.TemporaryDirectory(prefix="completion-ci-python-") as temporary:
            root = Path(temporary)
            (root / "evidence").mkdir()
            env = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
                   "P06_COMPLETION_ROOT": str(root)}
            result = subprocess.run([sys.executable, "-I", "-"], input=body, cwd=ROOT, env=env,
                                    text=True, capture_output=True, timeout=10)
            data = json.loads((root / "evidence/python-provision.json").read_text())
            self.assertEqual(data["python_version"], list(sys.version_info[:3]))
            self.assertEqual(Path(data["executable"]).resolve(), Path(sys.executable).resolve())
            matching = (data["python_version"] == [3, 12, 14] and data["implementation"] == "CPython"
                        and data["platform"] == "linux"
                        and Path(data["python3_on_path"]).resolve() == Path(sys.executable).resolve())
            self.assertEqual(result.returncode, 0 if matching else 1, result.stderr)

    def test_actual_interpreter_path_mismatch_is_retained_and_rejected(self):
        body = heredoc_body(self.one("name", PYTHON_IDENTITY), "python3 -I - <<'PY'")
        with tempfile.TemporaryDirectory(prefix="completion-ci-python-mismatch-") as temporary:
            root = Path(temporary)
            (root / "evidence").mkdir()
            alternative = root / "python3"
            alternative.write_text('#!/bin/sh\nexit 97\n')
            alternative.chmod(0o700)
            env = {"PATH": str(root), "P06_COMPLETION_ROOT": str(root)}
            wrapper = ("import sys\nfrom unittest import mock\n"
                       "with mock.patch.object(sys, 'version_info', (3, 12, 14)):\n"
                       "    exec(" + repr(body) + ")\n")
            result = subprocess.run([sys.executable, "-I", "-"], input=wrapper, cwd=ROOT, env=env,
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertIn("Python interpreter identity differs", result.stderr)
            data = json.loads((root / "evidence/python-provision.json").read_text())
            self.assertEqual(data["python_version"], [3, 12, 14])
            self.assertEqual(Path(data["python3_on_path"]), alternative)
            self.assertEqual(Path(data["executable"]).resolve(), Path(sys.executable).resolve())
            self.assertNotEqual(Path(data["python3_on_path"]).resolve(), Path(data["executable"]).resolve())

    def test_every_shell_and_embedded_python_block_is_syntactically_valid(self):
        for step in self.steps:
            if "run" in step:
                with self.subTest(step=step.get("name", step.get("id"))):
                    result = subprocess.run(["bash", "-n"], input=script(step), text=True,
                                            capture_output=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
        for name, invocation in ((IDENTITY, "python3 - <<'PY'"), (PYTHON_IDENTITY, "python3 -I - <<'PY'")):
            compile(heredoc_body(self.one("name", name), invocation), name, "exec")


if __name__ == "__main__":
    unittest.main()
