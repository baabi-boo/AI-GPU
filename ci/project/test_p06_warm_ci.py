# SPDX-License-Identifier: Apache-2.0
"""Host-only checks of warm workflow scope, trust and failure retention."""

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
import p06_warm_contract as manifest
import p06_warm_execute as runner
from test_p05_ci_workflow import children, path_filters, scalars, script, steps, workflow
from test_p06_workspace_ci import covers, heredoc_body, one_command


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/p06-warm-workspace.yml"
PREPARE = "Verify clean source and relocate restored tools"
EXECUTE = "Execute all warm workspace pairs serially"


def required_sources():
    names = set(SOURCE_INPUTS + runner.SOURCE_FILES + runner.operator_run.SOURCE_FILES
                + runner.base.COPIED + runner.base.TOOLING + runner.base.CORPUS)
    names.update(item["path"] for item in runner.LOADED_HELPERS)
    for directory in runner.base.SOURCE_ROOTS:
        names.update(path.relative_to(ROOT).as_posix()
                     for path in (ROOT / directory).rglob("*")
                     if path.is_file() and (path.suffix in runner.base.SOURCE_SUFFIXES
                                            or path.suffix == ".inc" or path.name == "Makefile"))
    names.update(path.relative_to(ROOT).as_posix() for path in (ROOT / "tests/runtime").glob("*.cpp"))
    names.update({"Makefile.in", "config.mk.in", "profiles/p02-tfr.json", "third_party/Makefile",
                  "ci/project/test_p06_warm_runner.py", Path(__file__).relative_to(ROOT).as_posix()})
    return names


class WarmWorkspaceWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = workflow(WORKFLOW)
        cls.events = children(cls.workflow, "on", 2)
        cls.jobs = children(cls.workflow, "jobs", 2)
        cls.job = children(cls.jobs, "experiment", 4)
        cls.steps = steps(cls.job)

    def one(self, key, value, sequence=None):
        found = [step for step in (self.steps if sequence is None else sequence)
                 if step.get(key, (None,))[0] == value]
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

    def test_retained_transitive_native_preparation_and_counter_inputs_trigger(self):
        self.assertTrue({".github/workflows/p04-model.yml", "third_party/Makefile",
                         "tests/regression/ai_bench_common/counters.h"} <= set(runner.SOURCE_FILES))
        for event in ("push", "pull_request"):
            patterns = path_filters(self.events, event)
            self.assertEqual(sorted(name for name in required_sources() if not covers(patterns, name)), [],
                             event + " omits a retained or native build input")

    def test_missing_warm_or_preparation_source_filters_are_detectable(self):
        patterns = path_filters(self.events, "push")
        witnesses = {
            ".github/workflows/p04-model.yml": ".github/workflows/p04-model.yml",
            "tests/regression/ai_warm_workspace/**": "tests/regression/ai_warm_workspace/observer.cpp",
            "tests/regression/ai_bench_common/**": "tests/regression/ai_bench_common/counters.h",
            "tests/regression/sgemm_tcu/**": "tests/regression/sgemm_tcu/p02_fixtures.h",
            "third_party/**": "third_party/Makefile",
            "ci/project/**": "ci/project/p06_warm_compiler_records.py",
            "docs/designs/warm_workspace_benchmark_v1.md": "docs/designs/warm_workspace_benchmark_v1.md",
        }
        for pattern, name in witnesses.items():
            with self.subTest(path=name):
                self.assertIn(name, required_sources())
                self.assertTrue(covers(patterns, name))
                self.assertFalse(covers(patterns - {pattern}, name))

    def test_one_serial_hosted_job_has_fixed_scope_and_resource_bounds(self):
        self.assertEqual(set(self.jobs), {"experiment"})
        self.assertEqual(set(self.job), {"name", "runs-on", "timeout-minutes", "defaults", "env", "steps"})
        self.assertEqual(self.job["runs-on"], ("ubuntu-22.04", []))
        self.assertEqual(self.job["timeout-minutes"], ("90", []))
        defaults = children(self.job, "defaults", 6)
        self.assertEqual(set(defaults), {"run"})
        self.assertEqual(scalars(children(defaults, "run", 8)), {"shell": "bash"})
        self.assertEqual(scalars(children(self.job, "env", 6)), {
            "P06_WARM_BACKEND": "simx", "P06_WARM_FORMAT": "both",
            "PYTHONDONTWRITEBYTECODE": "'1'", "MAKEFLAGS": "'-j2'", "THREADS": "'2'",
            "CMAKE_BUILD_PARALLEL_LEVEL": "'2'", "CCACHE_DISABLE": "'1'", "OBJCACHE": "''",
        })
        self.assertEqual(runner.BUDGET, {"min_free_bytes": 15 * 1024**3,
                                      "max_rss_bytes": 4 * 1024**3, "max_log_bytes": 16 * 1024**2})
        self.assertEqual((p04_ci_prepare.MIN_FREE_BYTES, p04_ci_prepare.MAX_RSS_BYTES),
                         (15 * 1024**3, 4 * 1024**3))
        plan = manifest.process_plan(manifest.load_contract())
        self.assertEqual(len(plan), 24)
        self.assertEqual({row["backend"] for row in plan}, {"simx"})
        self.assertEqual({row["format"] for row in plan}, {"fp16", "bf16"})
        self.assertEqual({row["policy"] for row in plan}, {"per_operation", "reusable_single_tile"})
        self.assertNotRegex(WORKFLOW.read_text(), r"matrix\.|max-parallel|strategy:")

    def test_read_only_hosted_trust_has_no_failure_suppression_or_cache_write(self):
        self.assertEqual(scalars(children(self.workflow, "permissions", 2)), {"contents": "read"})
        self.assertEqual(scalars(children(self.workflow, "concurrency", 2)), {
            "group": "p06-warm-workspace-${{ github.event_name }}-${{ github.ref }}",
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
            r"secrets\s*\.|pull_request_target|workflow_run|self-hosted|write-all|id-token:|contents:\s*write|continue-on-error")

    def test_pinned_restore_only_inputs_precede_clean_source_preparation(self):
        toolchain, dependencies = self.one("id", "toolchain"), self.one("id", "dependencies")
        self.assertEqual(scalars(children(toolchain, "with", 10)), {
            "path": "tools", "key": "${{ runner.os }}-toolchain-${{ steps.pins.outputs.toolchain }}-lite",
            "restore-keys": "${{ runner.os }}-toolchain-${{ steps.pins.outputs.toolchain }}-"})
        self.assertEqual(scalars(children(dependencies, "with", 10)), {
            "path": "third_party", "key": "${{ runner.os }}-thirdparty-${{ hashFiles('third_party/Makefile', '.gitmodules') }}"})
        self.assertEqual(script(self.one("id", "pins")).splitlines(), [
            "set -euo pipefail", "P06_WARM_TOOLCHAIN_ID=$(bash ci/toolchain_rev.sh)",
            '[[ "$P06_WARM_TOOLCHAIN_ID" =~ ^[A-Za-z0-9._-]+-[0-9a-f]{40}$ ]]',
            'echo "toolchain=$P06_WARM_TOOLCHAIN_ID" >> "$GITHUB_OUTPUT"'])
        install = self.one("name", "Install baseline host dependencies")
        self.assertEqual(install["if"], (
            "steps.toolchain.outputs.cache-matched-key != '' && steps.dependencies.outputs.cache-matched-key != ''", []))
        self.assertEqual(install["timeout-minutes"], ("15", []))
        self.assertEqual(one_command(install, pipefail=True), ["sudo", "bash", "ci/install_dependencies.sh",
            "2>&1", "|", "tee", "$P06_WARM_ROOT/evidence/host-dependencies.log"])
        for step in self.steps:
            if "run" in step:
                self.assertNotRegex(script(step), r"toolchain_install|(?:curl|wget)\s|make\s.*third_party|git clone")
        order = [self.one("uses", "actions/checkout@v4"), self.one("name", "Initialize retained job identity"),
                 self.one("uses", "actions/setup-python@v5"), self.one("name", "Retain and verify Python interpreter identity"),
                 self.one("id", "pins"), toolchain, dependencies, install, self.one("name", PREPARE),
                 self.one("name", EXECUTE), self.one("uses", "actions/upload-artifact@v4")]
        self.assertEqual(self.steps, order)

    def test_preparation_binds_both_formats_and_inherited_source_cache_receipts(self):
        prepare = self.one("name", PREPARE)
        self.assertEqual(set(prepare), {"name", "env", "run"})
        self.assertEqual(scalars(children(prepare, "env", 10)), {
            "P06_WARM_TOOLCHAIN_ID": "${{ steps.pins.outputs.toolchain }}",
            "P06_WARM_TOOLCHAIN_CACHE": "${{ steps.toolchain.outputs.cache-matched-key }}",
            "P06_WARM_DEPENDENCY_CACHE": "${{ steps.dependencies.outputs.cache-matched-key }}",
            "P06_WARM_DEPENDENCY_KEY": "${{ runner.os }}-thirdparty-${{ hashFiles('third_party/Makefile', '.gitmodules') }}"})
        self.assertEqual(one_command(prepare, pipefail=True), [
            "python3", "ci/project/p04_ci_prepare.py", "--source-dir", "$PWD", "--workspace-dir", "$P06_WARM_ROOT",
            "--expected-revision", "$GITHUB_SHA", "--toolchain-id", "$P06_WARM_TOOLCHAIN_ID",
            "--toolchain-cache-key", "$P06_WARM_TOOLCHAIN_CACHE", "--third-party-cache-key", "$P06_WARM_DEPENDENCY_CACHE",
            "--expected-third-party-key", "$P06_WARM_DEPENDENCY_KEY", "--backend", "$P06_WARM_BACKEND",
            "--format", "$P06_WARM_FORMAT", "2>&1", "|", "tee", "$P06_WARM_ROOT/evidence/preparation.log"])
        self.assertTrue({"ci/project/p04_ci_prepare.py", ".github/workflows/p04-model.yml",
                         "ci/toolchain_rev.sh", "ci/install_dependencies.sh", "third_party/Makefile"}
                        <= set(runner.SOURCE_FILES))

    def test_one_execution_invocation_has_no_sample_policy_or_threshold_selector(self):
        execute = self.one("name", EXECUTE)
        self.assertEqual(set(execute), {"name", "run"})
        self.assertEqual(one_command(execute, pipefail=True), [
            "python3", "ci/project/p06_warm_execute.py", "run", "--source-dir", "$PWD",
            "--tools-dir", "$P06_WARM_ROOT/tools", "--work-dir", "$P06_WARM_ROOT/work",
            "--output", "$P06_WARM_ROOT/evidence/warm-workspace", "--jobs", "2",
            "--timeout-seconds", "1800", "--run-timeout-seconds", "180",
            "2>&1", "|", "tee", "$P06_WARM_ROOT/evidence/execution.log"])
        parser = runner.argument_parser()
        options = {option for action in parser._actions for option in action.option_strings}
        self.assertEqual(options, {"-h", "--help", "--source-dir", "--tools-dir", "--work-dir", "--output",
                                   "--host-bin", "--jobs", "--timeout-seconds", "--run-timeout-seconds"})
        basic = ["run", "--tools-dir", "/unused/tools", "--work-dir", "/unused/work", "--output", "/unused/output"]
        args = parser.parse_args(basic)
        self.assertEqual((args.jobs, args.timeout_seconds, args.run_timeout_seconds), (2, 1800, 180))
        for option in ("--backend", "--format", "--policy", "--samples", "--pairs", "--iterations",
                       "--threshold", "--outlier", "--development"):
            with self.subTest(option=option), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                parser.parse_args([*basic, option, "1"])
            self.assertEqual(error.exception.code, 2)

    def test_failed_producers_retain_stdout_stderr_and_fail_the_actual_pipelines(self):
        for label, log_name in ((PREPARE, "preparation.log"), (EXECUTE, "execution.log")):
            with self.subTest(step=label), tempfile.TemporaryDirectory(prefix="warm-ci-pipeline-") as temporary:
                root = Path(temporary)
                (root / "evidence").mkdir()
                stub = root / "python3"
                stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$P06_CI_ARGUMENTS"\n'
                                'printf "synthetic producer failed\\n"\n'
                                'printf "synthetic stderr\\n" >&2\nexit 37\n')
                stub.chmod(0o700)
                env = {"PATH": str(root) + os.pathsep + os.defpath, "P06_WARM_ROOT": str(root),
                       "P06_CI_ARGUMENTS": str(root / "arguments"), "GITHUB_SHA": "1" * 40,
                       "P06_WARM_BACKEND": "simx", "P06_WARM_FORMAT": "both",
                       **{name: "synthetic-unused" for name in ("P06_WARM_TOOLCHAIN_ID", "P06_WARM_TOOLCHAIN_CACHE",
                            "P06_WARM_DEPENDENCY_CACHE", "P06_WARM_DEPENDENCY_KEY")}}
                result = subprocess.run(["/bin/bash", "-c", script(self.one("name", label))],
                    cwd=ROOT, env=env, text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 37, result.stderr)
                self.assertEqual((root / "evidence" / log_name).read_text(),
                                 "synthetic producer failed\nsynthetic stderr\n")
                self.assertEqual((root / "arguments").read_text().splitlines()[0],
                                 "ci/project/p04_ci_prepare.py" if label == PREPARE else "ci/project/p06_warm_execute.py")

    def test_failure_artifacts_include_every_evidence_file_with_unique_attempt_identity(self):
        upload = self.one("uses", "actions/upload-artifact@v4")
        self.assertEqual(set(upload), {"name", "if", "uses", "with"})
        self.assertEqual(upload["if"], ("always()", []))
        self.assertEqual(scalars(children(upload, "with", 10)), {
            "name": "p06-warm-workspace-${{ github.sha }}-run${{ github.run_id }}-attempt${{ github.run_attempt }}",
            "path": "${{ runner.temp }}/p06-warm-workspace/evidence", "if-no-files-found": "error",
            "retention-days": "30", "compression-level": "6", "include-hidden-files": "true"})
        self.assertEqual(self.steps[-1], upload)

    def test_actual_initialization_records_are_explicitly_pre_execution_and_not_reused(self):
        body = heredoc_body(self.one("name", "Initialize retained job identity"), "python3 - <<'PY'")
        with tempfile.TemporaryDirectory(prefix="warm-ci-identity-") as temporary:
            root = Path(temporary)
            env = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
                   "RUNNER_TEMP": str(root), "GITHUB_ENV": str(root / "github-env"),
                   "GITHUB_SHA": "1" * 40, "GITHUB_EVENT_NAME": "pull_request", "GITHUB_RUN_ID": "123",
                   "GITHUB_RUN_ATTEMPT": "2", "GITHUB_JOB": "experiment", "GITHUB_REPOSITORY": "host-test/synthetic",
                   "GITHUB_REF": "refs/pull/1/merge", "P06_WARM_BACKEND": "simx", "P06_WARM_FORMAT": "both"}
            result = subprocess.run([sys.executable, "-I", "-"], input=body, cwd=ROOT, env=env,
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = root / "p06-warm-workspace/evidence"
            self.assertEqual((evidence / "workflow.yml").read_bytes(), WORKFLOW.read_bytes())
            data = json.loads((evidence / "job.json").read_text())
            expected = {key: value for key, value in env.items() if key.startswith(("GITHUB_", "P06_WARM_"))
                        and key != "GITHUB_ENV"}
            self.assertEqual(data, dict(expected, scope="matched-warm-context-workspace-experiment",
                record_stage="job-initialization", native_execution="not_run", acceptance_claimed=False,
                workflow_sha256=hashlib.sha256(WORKFLOW.read_bytes()).hexdigest()))
            self.assertEqual((root / "github-env").read_text(), "P06_WARM_ROOT=" + str(root / "p06-warm-workspace") + "\n")
            repeated = subprocess.run([sys.executable, "-I", "-"], input=body, cwd=ROOT, env=env,
                                      text=True, capture_output=True, timeout=10)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertEqual(json.loads((evidence / "job.json").read_text()), data)

    def test_pinned_interpreter_probe_retains_actual_identity_before_rejection(self):
        setup = self.one("uses", "actions/setup-python@v5")
        self.assertEqual(scalars(children(setup, "with", 10)), {
            "python-version": "'3.12.14'", "architecture": "x64", "check-latest": "false"})
        body = heredoc_body(self.one("name", "Retain and verify Python interpreter identity"), "python3 -I - <<'PY'")
        for token in ("data['python_version'] != [3, 12, 14]", "data['implementation'] != 'CPython'",
                      "data['platform'] != 'linux'", "Path(data['python3_on_path']).resolve() != Path(sys.executable).resolve()",
                      "raise SystemExit("):
            self.assertIn(token, body)
        with tempfile.TemporaryDirectory(prefix="warm-ci-python-") as temporary:
            root = Path(temporary)
            (root / "evidence").mkdir()
            env = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath, "P06_WARM_ROOT": str(root)}
            result = subprocess.run([sys.executable, "-I", "-"], input=body, cwd=ROOT, env=env,
                                    text=True, capture_output=True, timeout=10)
            data = json.loads((root / "evidence/python-provision.json").read_text())
            self.assertEqual(data["python_version"], list(sys.version_info[:3]))
            self.assertEqual(Path(data["executable"]).resolve(), Path(sys.executable).resolve())
            matching = (data["python_version"] == [3, 12, 14] and data["implementation"] == "CPython"
                        and data["platform"] == "linux"
                        and Path(data["python3_on_path"]).resolve() == Path(sys.executable).resolve())
            self.assertEqual(result.returncode, 0 if matching else 1, result.stderr)

    def test_every_shell_and_python_block_is_syntactically_valid(self):
        for step in self.steps:
            if "run" in step:
                with self.subTest(step=step.get("name", step.get("id"))):
                    result = subprocess.run(["bash", "-n"], input=script(step), text=True,
                                            capture_output=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
        for name, invocation in (("Initialize retained job identity", "python3 - <<'PY'"),
                                 ("Retain and verify Python interpreter identity", "python3 -I - <<'PY'")):
            compile(heredoc_body(self.one("name", name), invocation), name, "exec")

    def test_interpreter_path_mismatch_is_retained_and_fails_closed(self):
        body = heredoc_body(self.one("name", "Retain and verify Python interpreter identity"), "python3 -I - <<'PY'")
        with tempfile.TemporaryDirectory(prefix="warm-ci-python-mismatch-") as temporary:
            root = Path(temporary)
            (root / "evidence").mkdir()
            alternative = root / "python3"
            alternative.write_text('#!/bin/sh\nexit 97\n')
            alternative.chmod(0o700)
            env = {"PATH": str(root), "P06_WARM_ROOT": str(root)}
            result = subprocess.run([sys.executable, "-I", "-"], input=body, cwd=ROOT, env=env,
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertIn("Python interpreter identity differs", result.stderr)
            data = json.loads((root / "evidence/python-provision.json").read_text())
            self.assertEqual(Path(data["python3_on_path"]), alternative)
            self.assertEqual(Path(data["executable"]).resolve(), Path(sys.executable).resolve())
            self.assertNotEqual(Path(data["python3_on_path"]).resolve(), Path(data["executable"]).resolve())

    def test_governance_covers_warm_inputs_and_preserves_unconditional_checks(self):
        governance = workflow(ROOT / ".github/workflows/project-governance.yml")
        events = children(governance, "on", 2)
        required = {".github/workflows/p06-warm-workspace.yml", "docs/designs/warm_workspace_benchmark_v1.md",
                    "ci/project/p06_warm_contract.py", "ci/project/p06_warm_contract.json",
                    "ci/project/p06_warm_execute.py", "ci/project/p06_warm_records.py",
                    "ci/project/p06_warm_compiler_records.py", Path(__file__).relative_to(ROOT).as_posix()}
        required.update(path.relative_to(ROOT).as_posix() for path in (ROOT / runner.APP).iterdir() if path.is_file())
        for event in ("push", "pull_request"):
            patterns = path_filters(events, event)
            self.assertEqual(sorted(name for name in required if not covers(patterns, name)), [], event)
        job = children(children(governance, "jobs", 2), "governance", 4)
        self.assertEqual(set(job), {"runs-on", "timeout-minutes", "env", "steps"})
        self.assertEqual(job["runs-on"], ("ubuntu-24.04", []))
        self.assertEqual(job["timeout-minutes"], ("30", []))
        checks = {"Inspect governance prerequisites": "python3 ci/project/preflight.py --tier governance",
                  "Validate project structure and evidence": "python3 ci/project/check_project.py",
                  "Check published baseline packet consistency": "python3 ci/project/check_baseline_packets.py",
                  "Test governance tooling": "python3 -m unittest discover -s ci/project -p 'test_*.py'"}
        for name, expected in checks.items():
            step = self.one("name", name, steps(job))
            self.assertEqual(set(step), {"name", "run"})
            self.assertEqual(script(step), expected)


if __name__ == "__main__":
    unittest.main()
