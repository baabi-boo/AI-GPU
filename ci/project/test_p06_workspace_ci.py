# SPDX-License-Identifier: Apache-2.0
"""Python-only checks of workspace workflow scope, trust and failure retention."""

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest

from baseline_inventory import SOURCE_INPUTS
import p04_ci_prepare
import p06_workspace_execute as runner
from test_p05_ci_workflow import children, path_filters, scalars, script, steps, workflow


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/p06-workspace.yml"


def covers(patterns, path):
    return any(re.fullmatch(re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", "[^/]*"), path)
               for pattern in patterns)


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
                  "ci/project/test_p06_workspace_runner.py", Path(__file__).relative_to(ROOT).as_posix()})
    return names


def one_command(step, *, pipefail=False):
    lines = script(step).replace("\\\n", " ").splitlines()
    if pipefail:
        if not lines or lines.pop(0) != "set -euo pipefail":
            raise AssertionError("retained pipeline must enable shell error propagation")
    if len(lines) != 1:
        raise AssertionError("expected exactly one bounded command")
    return shlex.split(lines[0])


def heredoc_body(step, invocation):
    lines = script(step).splitlines()
    if lines[0] != invocation or lines[-1] != "PY":
        raise AssertionError("expected one bounded Python heredoc")
    return "\n".join(lines[1:-1])


class SerialWorkspaceWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = workflow(WORKFLOW)
        cls.events = children(cls.workflow, "on", 2)
        cls.jobs = children(cls.workflow, "jobs", 2)
        cls.job = children(cls.jobs, "qualification", 4)
        cls.steps = steps(cls.job)

    def one(self, key, value):
        found = [step for step in self.steps if step.get(key, (None,))[0] == value]
        self.assertEqual(len(found), 1, (key, value))
        return found[0]

    def test_only_master_push_pull_request_and_manual_events_with_positive_filters(self):
        self.assertEqual(set(self.workflow), {"name", "on", "permissions", "concurrency", "jobs"})
        self.assertEqual(set(self.events), {"push", "pull_request", "workflow_dispatch"})
        self.assertEqual(self.events["workflow_dispatch"], ("", []))
        self.assertEqual(children(self.events, "push", 4)["branches"], ("[master]", []))
        self.assertEqual(set(children(self.events, "push", 4)), {"branches", "paths"})
        self.assertEqual(set(children(self.events, "pull_request", 4)), {"paths"})
        self.assertEqual(path_filters(self.events, "push"), path_filters(self.events, "pull_request"))

    def test_all_retained_transitive_and_new_workspace_inputs_trigger_both_events(self):
        for event in ("push", "pull_request"):
            patterns = path_filters(self.events, event)
            missing = sorted(name for name in required_sources() if not covers(patterns, name))
            self.assertEqual(missing, [], event + " omits retained or build input paths")

    def test_workspace_caller_contract_and_workflow_changes_also_run_host_governance(self):
        governance = children(workflow(ROOT / ".github/workflows/project-governance.yml"), "on", 2)
        inputs = {".github/workflows/p06-workspace.yml",
                  "docs/designs/serial_matmul_workspace_v1.md"}
        inputs.update(path.relative_to(ROOT).as_posix()
                      for path in (ROOT / runner.APP).iterdir() if path.is_file())
        for event in ("push", "pull_request"):
            patterns = path_filters(governance, event)
            self.assertEqual(sorted(name for name in inputs if not covers(patterns, name)), [],
                             event + " omits workspace inputs exercised by the host suite")

    def test_removed_workspace_or_inherited_source_filter_is_detectable(self):
        patterns = path_filters(self.events, "push")
        witnesses = {
            "tests/regression/ai_workspace/**": "tests/regression/ai_workspace/observer.cpp",
            "tests/regression/sgemm_tcu/**": "tests/regression/sgemm_tcu/p02_fixture_adapter.h",
            "tests/regression/ai_matmul/**": "tests/regression/ai_matmul/Makefile",
            "tests/runtime/**": "tests/runtime/test_ai_lifecycle.cpp",
            "ci/blackbox.sh": "ci/blackbox.sh", "Makefile.in": "Makefile.in",
        }
        for pattern, name in witnesses.items():
            with self.subTest(path=name):
                self.assertIn(name, required_sources())
                self.assertTrue(covers(patterns, name))
                self.assertFalse(covers(patterns - {pattern}, name))

    def test_hosted_four_variant_matrix_and_exact_resource_budgets(self):
        self.assertEqual(set(self.jobs), {"qualification"})
        self.assertEqual(set(self.job), {"name", "runs-on", "timeout-minutes", "defaults", "strategy", "env", "steps"})
        self.assertEqual(self.job["runs-on"], ("ubuntu-22.04", []))
        self.assertEqual(self.job["timeout-minutes"], ("90", []))
        strategy = children(self.job, "strategy", 6)
        self.assertEqual(set(strategy), {"fail-fast", "max-parallel", "matrix"})
        self.assertEqual(strategy["fail-fast"], ("false", []))
        self.assertEqual(strategy["max-parallel"], ("2", []))
        self.assertEqual(scalars(children(strategy, "matrix", 8)),
                         {"backend": "[simx, rtlsim]", "format": "[fp16, bf16]"})
        defaults = children(self.job, "defaults", 6)
        self.assertEqual(set(defaults), {"run"})
        self.assertEqual(scalars(children(defaults, "run", 8)), {"shell": "bash"})
        self.assertEqual(scalars(children(self.job, "env", 6)), {
            "P06_WORKSPACE_BACKEND": "${{ matrix.backend }}", "P06_WORKSPACE_FORMAT": "${{ matrix.format }}",
            "PYTHONDONTWRITEBYTECODE": "'1'", "MAKEFLAGS": "'-j2'", "THREADS": "'2'",
            "CMAKE_BUILD_PARALLEL_LEVEL": "'2'", "CCACHE_DISABLE": "'1'", "OBJCACHE": "''",
        })
        self.assertEqual(runner.BUDGET, {"min_free_bytes": 15 * 1024**3,
                                      "max_rss_bytes": 4 * 1024**3, "max_log_bytes": 16 * 1024**2})
        self.assertEqual((p04_ci_prepare.MIN_FREE_BYTES, p04_ci_prepare.MAX_RSS_BYTES),
                         (15 * 1024**3, 4 * 1024**3))
        args = runner.argument_parser().parse_args([
            "run", "--tools-dir", "/unused/tools", "--work-dir", "/unused/work", "--output", "/unused/output"])
        self.assertEqual((args.jobs, args.timeout_seconds, args.run_timeout_seconds), (2, 1800, 180))

    def test_read_only_token_checkout_and_no_fork_cache_write_or_failure_suppression(self):
        self.assertEqual(scalars(children(self.workflow, "permissions", 2)), {"contents": "read"})
        self.assertEqual(scalars(children(self.workflow, "concurrency", 2)), {
            "group": "p06-workspace-${{ github.event_name }}-${{ github.ref }}", "cancel-in-progress": "false"})
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
                            r"secrets\s*\.|pull_request_target|workflow_run|self-hosted|write-all|id-token:|contents:\s*write")

    def test_restore_only_cache_keys_are_pinned_before_clean_source_preparation(self):
        toolchain = self.one("id", "toolchain")
        dependencies = self.one("id", "dependencies")
        self.assertEqual(toolchain["uses"], ("actions/cache/restore@v4", []))
        self.assertEqual(dependencies["uses"], ("actions/cache/restore@v4", []))
        self.assertEqual(scalars(children(toolchain, "with", 10)), {
            "path": "tools", "key": "${{ runner.os }}-toolchain-${{ steps.pins.outputs.toolchain }}-lite",
            "restore-keys": "${{ runner.os }}-toolchain-${{ steps.pins.outputs.toolchain }}-"})
        self.assertEqual(scalars(children(dependencies, "with", 10)), {
            "path": "third_party", "key": "${{ runner.os }}-thirdparty-${{ hashFiles('third_party/Makefile', '.gitmodules') }}"})
        self.assertEqual(script(self.one("id", "pins")).splitlines(), [
            "set -euo pipefail", "P06_WORKSPACE_TOOLCHAIN_ID=$(bash ci/toolchain_rev.sh)",
            '[[ "$P06_WORKSPACE_TOOLCHAIN_ID" =~ ^[A-Za-z0-9._-]+-[0-9a-f]{40}$ ]]',
            'echo "toolchain=$P06_WORKSPACE_TOOLCHAIN_ID" >> "$GITHUB_OUTPUT"'])
        install = self.one("name", "Install baseline host dependencies")
        self.assertEqual(install["if"], (
            "steps.toolchain.outputs.cache-matched-key != '' && steps.dependencies.outputs.cache-matched-key != ''", []))
        self.assertEqual(install["timeout-minutes"], ("15", []))
        self.assertEqual(one_command(install, pipefail=True), ["sudo", "bash", "ci/install_dependencies.sh",
            "2>&1", "|", "tee", "$P06_WORKSPACE_ROOT/evidence/host-dependencies.log"])
        for step in self.steps:
            if "run" in step:
                self.assertNotRegex(script(step), r"toolchain_install|(?:curl|wget)\s|make\s.*third_party|git clone")
        ordered = [self.one("uses", "actions/checkout@v4"), self.one("name", "Initialize retained job identity"),
                   self.one("uses", "actions/setup-python@v5"), self.one("name", "Retain and verify Python interpreter identity"),
                   self.one("id", "pins"), toolchain, dependencies, install,
                   self.one("name", "Verify clean source and relocate restored tools"),
                   self.one("name", "Execute frozen workspace correctness variant"),
                   self.one("uses", "actions/upload-artifact@v4")]
        self.assertEqual([self.steps.index(step) for step in ordered], sorted(self.steps.index(step) for step in ordered))

    def test_prepare_and_execute_commands_bind_fresh_paths_without_scope_escape(self):
        prepare = self.one("name", "Verify clean source and relocate restored tools")
        self.assertEqual(set(prepare), {"name", "env", "run"})
        self.assertEqual(scalars(children(prepare, "env", 10)), {
            "P06_WORKSPACE_TOOLCHAIN_ID": "${{ steps.pins.outputs.toolchain }}",
            "P06_WORKSPACE_TOOLCHAIN_CACHE": "${{ steps.toolchain.outputs.cache-matched-key }}",
            "P06_WORKSPACE_DEPENDENCY_CACHE": "${{ steps.dependencies.outputs.cache-matched-key }}",
            "P06_WORKSPACE_DEPENDENCY_KEY": "${{ runner.os }}-thirdparty-${{ hashFiles('third_party/Makefile', '.gitmodules') }}"})
        self.assertEqual(one_command(prepare, pipefail=True), [
            "python3", "ci/project/p04_ci_prepare.py", "--source-dir", "$PWD", "--workspace-dir", "$P06_WORKSPACE_ROOT",
            "--expected-revision", "$GITHUB_SHA", "--toolchain-id", "$P06_WORKSPACE_TOOLCHAIN_ID",
            "--toolchain-cache-key", "$P06_WORKSPACE_TOOLCHAIN_CACHE", "--third-party-cache-key", "$P06_WORKSPACE_DEPENDENCY_CACHE",
            "--expected-third-party-key", "$P06_WORKSPACE_DEPENDENCY_KEY", "--backend", "$P06_WORKSPACE_BACKEND",
            "--format", "$P06_WORKSPACE_FORMAT", "2>&1", "|", "tee", "$P06_WORKSPACE_ROOT/evidence/preparation.log"])
        execute = self.one("name", "Execute frozen workspace correctness variant")
        self.assertEqual(set(execute), {"name", "run"})
        self.assertEqual(one_command(execute), [
            "python3", "ci/project/p06_workspace_execute.py", "run", "--source-dir", "$PWD",
            "--tools-dir", "$P06_WORKSPACE_ROOT/tools", "--work-dir", "$P06_WORKSPACE_ROOT/work",
            "--output", "$P06_WORKSPACE_ROOT/evidence/workspace", "--backend", "$P06_WORKSPACE_BACKEND",
            "--format", "$P06_WORKSPACE_FORMAT", "--jobs", "2", "--timeout-seconds", "1800", "--run-timeout-seconds", "180"])

    def test_failure_artifact_upload_is_unconditional_complete_and_unique(self):
        upload = self.one("uses", "actions/upload-artifact@v4")
        self.assertEqual(set(upload), {"name", "if", "uses", "with"})
        self.assertEqual(upload["if"], ("always()", []))
        self.assertEqual(scalars(children(upload, "with", 10)), {
            "name": "p06-workspace-${{ matrix.backend }}-${{ matrix.format }}-${{ github.sha }}-run${{ github.run_id }}-attempt${{ github.run_attempt }}",
            "path": "${{ runner.temp }}/p06-workspace/evidence", "if-no-files-found": "error",
            "retention-days": "30", "compression-level": "6", "include-hidden-files": "true"})
        self.assertEqual(self.steps[-1], upload)

    def test_actual_identity_block_retains_workflow_and_never_claims_native_execution(self):
        body = heredoc_body(self.one("name", "Initialize retained job identity"), "python3 - <<'PY'")
        with tempfile.TemporaryDirectory(prefix="workspace-ci-identity-") as temporary:
            root = Path(temporary)
            env = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
                   "RUNNER_TEMP": str(root), "GITHUB_ENV": str(root / "github-env"),
                   "GITHUB_SHA": "1" * 40, "GITHUB_EVENT_NAME": "pull_request", "GITHUB_RUN_ID": "123",
                   "GITHUB_RUN_ATTEMPT": "2", "GITHUB_JOB": "qualification", "GITHUB_REPOSITORY": "host-test/synthetic",
                   "GITHUB_REF": "refs/pull/1/merge", "P06_WORKSPACE_BACKEND": "rtlsim", "P06_WORKSPACE_FORMAT": "bf16"}
            result = subprocess.run([sys.executable, "-I", "-"], input=body, cwd=ROOT, env=env,
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = root / "p06-workspace/evidence"
            self.assertEqual((evidence / "workflow.yml").read_bytes(), WORKFLOW.read_bytes())
            data = json.loads((evidence / "job.json").read_text())
            expected = {key: value for key, value in env.items() if key.startswith(("GITHUB_", "P06_WORKSPACE_"))
                        and key != "GITHUB_ENV"}
            self.assertEqual(data, dict(expected, scope="native-serial-workspace-correctness",
                native_execution="not_run", acceptance_claimed=False,
                workflow_sha256=hashlib.sha256(WORKFLOW.read_bytes()).hexdigest()))
            self.assertEqual((root / "github-env").read_text(), "P06_WORKSPACE_ROOT=" + str(root / "p06-workspace") + "\n")
            repeated = subprocess.run([sys.executable, "-I", "-"], input=body, cwd=ROOT, env=env,
                                      text=True, capture_output=True, timeout=10)
            self.assertNotEqual(repeated.returncode, 0, "existing evidence must never be silently reused")
            self.assertEqual(json.loads((evidence / "job.json").read_text()), data)

    def test_python_pin_and_real_identity_probe_retain_mismatches_before_failure(self):
        setup = self.one("uses", "actions/setup-python@v5")
        self.assertEqual(scalars(children(setup, "with", 10)), {
            "python-version": "'3.12.14'", "architecture": "x64", "check-latest": "false"})
        body = heredoc_body(self.one("name", "Retain and verify Python interpreter identity"), "python3 -I - <<'PY'")
        for token in ("data['python_version'] != [3, 12, 14]", "data['implementation'] != 'CPython'",
                      "data['platform'] != 'linux'", "Path(data['python3_on_path']).resolve() != Path(sys.executable).resolve()",
                      "raise SystemExit("):
            self.assertIn(token, body)
        with tempfile.TemporaryDirectory(prefix="workspace-ci-python-") as temporary:
            root = Path(temporary)
            (root / "evidence").mkdir()
            env = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
                   "P06_WORKSPACE_ROOT": str(root)}
            result = subprocess.run([sys.executable, "-I", "-"], input=body, cwd=ROOT, env=env,
                                    text=True, capture_output=True, timeout=10)
            data = json.loads((root / "evidence/python-provision.json").read_text())
            self.assertEqual(data["python_version"], list(sys.version_info[:3]))
            self.assertEqual(Path(data["executable"]).resolve(), Path(sys.executable).resolve())
            matching = (data["python_version"] == [3, 12, 14] and data["implementation"] == "CPython"
                        and data["platform"] == "linux"
                        and Path(data["python3_on_path"]).resolve() == Path(sys.executable).resolve())
            self.assertEqual(result.returncode, 0 if matching else 1, result.stderr)
            if not matching:
                self.assertIn("Python interpreter identity differs", result.stderr)

    def test_each_shell_block_is_valid_without_executing_workflow_commands(self):
        for step in self.steps:
            if "run" in step:
                with self.subTest(step=step.get("name", step.get("id"))):
                    result = subprocess.run(["bash", "-n"], input=script(step), text=True,
                                            capture_output=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
