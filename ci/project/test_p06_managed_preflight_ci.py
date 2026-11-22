# SPDX-License-Identifier: Apache-2.0
"""Bounded host checks of managed preflight workflow scope and failure paths."""

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
import p06_managed_preflight_contract as contract
import p06_managed_preflight_execute as runner
import p06_warm_contract as warm
from test_p05_ci_workflow import children, path_filters, scalars, script, steps, workflow
from test_p06_workspace_ci import covers, one_command


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/p06-managed-preflight.yml"
INITIALIZE = "Initialize retained job identity and resource observations"
INTERPRETER = "Retain and verify Python interpreter identity"
PREPARE = "Verify clean source and relocate restored tools"
EXECUTE = "Execute all managed preflight processes serially"
CLAIMS = (
    "qualified", "ready_for_warm", "warm_execution", "full_warm_coverage",
    "acceptance_claimed", "phase_acceptance", "performance_acceptance",
)


def required_sources():
    names = set(SOURCE_INPUTS + runner.SOURCE_FILES + runner.operator_run.SOURCE_FILES
                + runner.base.COPIED + runner.base.TOOLING + runner.base.CORPUS)
    names.update(row["path"] for row in runner.LOADED_HELPERS)
    for directory in runner.base.SOURCE_ROOTS:
        names.update(path.relative_to(ROOT).as_posix()
                     for path in (ROOT / directory).rglob("*")
                     if path.is_file() and (path.suffix in runner.base.SOURCE_SUFFIXES
                                            or path.suffix == ".inc" or path.name == "Makefile"))
    names.update(path.relative_to(ROOT).as_posix()
                 for path in (ROOT / "tests/runtime").glob("*.cpp"))
    names.update({
        "Makefile.in", "config.mk.in", "profiles/p02-tfr.json", "third_party/Makefile",
        ".github/workflows/p06-warm-workspace.yml", "tests/regression/ai_counter_preflight/hooks.h",
        "ci/project/test_p06_managed_preflight_contract.py", Path(__file__).relative_to(ROOT).as_posix(),
    })
    return names


def python_body(step, *, isolated=False):
    lines = script(step).splitlines()
    invocation = "python3 -I - <<'PY'" if isolated else "python3 - <<'PY'"
    if lines[:2] != ["set -euo pipefail", invocation] or lines[-1] != "PY":
        raise AssertionError("expected one bounded Python heredoc with shell failure propagation")
    return "\n".join(lines[2:-1])


def host_environment(root):
    return {
        "PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1", "RUNNER_TEMP": str(root),
        "GITHUB_ENV": str(root / "environment"), "GITHUB_SHA": "1" * 40,
        "GITHUB_EVENT_NAME": "pull_request", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_JOB": "managed-preflight", "GITHUB_REPOSITORY": "example/AI-GPU",
        "GITHUB_REF": "refs/pull/7/merge",
    }


class ManagedPreflightWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = workflow(WORKFLOW)
        cls.events = children(cls.workflow, "on", 2)
        cls.jobs = children(cls.workflow, "jobs", 2)
        cls.job = children(cls.jobs, "managed-preflight", 4)
        cls.steps = steps(cls.job)

    def one(self, key, value, sequence=None):
        found = [step for step in (self.steps if sequence is None else sequence)
                 if step.get(key, (None,))[0] == value]
        self.assertEqual(len(found), 1, (key, value))
        return found[0]

    def test_master_push_pull_request_and_manual_dispatch_have_no_scope_overrides(self):
        self.assertEqual(set(self.workflow), {"name", "on", "permissions", "concurrency", "jobs"})
        self.assertEqual(set(self.events), {"push", "pull_request", "workflow_dispatch"})
        self.assertEqual(self.events["workflow_dispatch"], ("", []))
        self.assertEqual(children(self.events, "push", 4)["branches"], ("[master]", []))
        self.assertEqual(set(children(self.events, "push", 4)), {"branches", "paths"})
        self.assertEqual(set(children(self.events, "pull_request", 4)), {"paths"})
        self.assertEqual(path_filters(self.events, "push"), path_filters(self.events, "pull_request"))

    def test_both_events_cover_all_retained_build_and_new_measurement_sources(self):
        names = required_sources()
        self.assertTrue({"tests/regression/ai_counter_preflight/hooks.cpp",
                         "tests/regression/ai_counter_preflight/backend.mk",
                         "tests/regression/ai_warm_workspace/main.cpp",
                         "ci/project/p06_managed_preflight_records.py"} <= names)
        for event in ("push", "pull_request"):
            with self.subTest(event=event):
                patterns = path_filters(self.events, event)
                self.assertEqual(sorted(name for name in names if not covers(patterns, name)), [])

    def test_removed_critical_filters_leave_detectable_trigger_gaps(self):
        patterns = path_filters(self.events, "push")
        witnesses = {
            "tests/regression/ai_counter_preflight/**": "tests/regression/ai_counter_preflight/hooks.cpp",
            "tests/regression/ai_warm_workspace/**": "tests/regression/ai_warm_workspace/main.cpp",
            "ci/project/**": "ci/project/p06_managed_preflight_execute.py",
            ".github/workflows/p04-model.yml": ".github/workflows/p04-model.yml",
            "docs/designs/managed_counter_preflight_v1.md": "docs/designs/managed_counter_preflight_v1.md",
            "third_party/**": "third_party/ramulator/libramulator.so",
        }
        for pattern, path in witnesses.items():
            with self.subTest(path=path):
                self.assertTrue(covers(patterns, path))
                self.assertFalse(covers(patterns - {pattern}, path))

    def test_new_workflow_caller_contract_and_helpers_trigger_governance(self):
        governance = children(workflow(ROOT / ".github/workflows/project-governance.yml"), "on", 2)
        names = {WORKFLOW.relative_to(ROOT).as_posix(), "docs/designs/managed_counter_preflight_v1.md"}
        names.update(path.relative_to(ROOT).as_posix()
                     for path in (ROOT / contract.APP).iterdir() if path.is_file())
        names.update(path.relative_to(ROOT).as_posix()
                     for path in (ROOT / "ci/project").glob("*managed_preflight*.py"))
        for event in ("push", "pull_request"):
            patterns = path_filters(governance, event)
            self.assertEqual(sorted(name for name in names if not covers(patterns, name)), [], event)

    def test_one_serial_hosted_job_has_fixed_resource_limits(self):
        self.assertEqual(set(self.jobs), {"managed-preflight"})
        self.assertEqual(set(self.job), {"name", "runs-on", "timeout-minutes", "defaults", "env", "steps"})
        self.assertEqual(self.job["runs-on"], ("ubuntu-22.04", []))
        self.assertEqual(self.job["timeout-minutes"], ("90", []))
        defaults = children(self.job, "defaults", 6)
        self.assertEqual(scalars(children(defaults, "run", 8)), {"shell": "bash"})
        self.assertEqual(runner.BUDGET, {"min_free_bytes": 15 * 1024**3,
                                      "max_rss_bytes": 4 * 1024**3, "max_log_bytes": 16 * 1024**2})
        self.assertEqual((p04_ci_prepare.MIN_FREE_BYTES, p04_ci_prepare.MAX_RSS_BYTES),
                         (15 * 1024**3, 4 * 1024**3))
        self.assertNotRegex(WORKFLOW.read_text(), r"matrix\.|max-parallel|strategy:|self-hosted")

    def test_single_worker_survives_clean_runner_environment_with_two_build_jobs(self):
        environment = scalars(children(self.job, "env", 6))
        self.assertEqual(environment, {
            "PYTHONDONTWRITEBYTECODE": "'1'", "MAKEFLAGS": "'-j2'", "THREADS": "'1'",
            "CMAKE_BUILD_PARALLEL_LEVEL": "'2'", "CCACHE_DISABLE": "'1'", "OBJCACHE": "''",
        })
        for jobs in (1, 2):
            clean = runner.clean_environment({"host_bin": None, "work": Path("/unused/work")}, jobs)
            self.assertEqual(clean["THREADS"], "1")
            self.assertEqual(clean["MAKEFLAGS"], "-j" + str(jobs))
            self.assertEqual(clean["CMAKE_BUILD_PARALLEL_LEVEL"], str(jobs))
            self.assertEqual(clean["PATH"].split(os.pathsep)[0], str(Path(sys.executable).parent))
        for step in self.steps:
            if "env" in step:
                self.assertNotIn("THREADS", children(step, "env", 10))

    def test_read_only_checkout_and_workflow_cannot_suppress_failed_execution(self):
        self.assertEqual(scalars(children(self.workflow, "permissions", 2)), {"contents": "read"})
        self.assertEqual(scalars(children(self.workflow, "concurrency", 2)), {
            "group": "p06-managed-preflight-${{ github.event_name }}-${{ github.ref }}",
            "cancel-in-progress": "false",
        })
        self.assertEqual(scalars(children(self.one("uses", "actions/checkout@v4"), "with", 10)), {
            "fetch-depth": "1", "submodules": "recursive", "persist-credentials": "false",
        })
        for step in self.steps:
            self.assertTrue(set(step) <= {"name", "uses", "with", "run", "id", "if", "env", "timeout-minutes"})
            if "if" in step:
                self.assertIn(step, [self.one("name", "Install baseline host dependencies"),
                                     self.one("uses", "actions/upload-artifact@v4")])
            if "run" in step:
                self.assertNotRegex(script(step), r"\|\|\s*true|set\s+\+|(?:^|\s)exit\s+0|git\s+push|gh\s+")
        self.assertNotRegex(WORKFLOW.read_text(),
                            r"secrets\s*\.|pull_request_target|workflow_run|write-all|id-token:|continue-on-error")

    def test_cache_actions_restore_pinned_inputs_without_writing_cache(self):
        toolchain, dependencies = self.one("id", "toolchain"), self.one("id", "dependencies")
        for step in (toolchain, dependencies):
            self.assertEqual(step["uses"], ("actions/cache/restore@v4", []))
        self.assertEqual(scalars(children(toolchain, "with", 10)), {
            "path": "tools", "key": "${{ runner.os }}-toolchain-${{ steps.pins.outputs.toolchain }}-lite",
            "restore-keys": "${{ runner.os }}-toolchain-${{ steps.pins.outputs.toolchain }}-",
        })
        self.assertEqual(scalars(children(dependencies, "with", 10)), {
            "path": "third_party", "key": "${{ runner.os }}-thirdparty-${{ hashFiles('third_party/Makefile', '.gitmodules') }}",
        })
        self.assertEqual([step["uses"][0] for step in self.steps if "uses" in step], [
            "actions/checkout@v4", "actions/setup-python@v5", "actions/cache/restore@v4",
            "actions/cache/restore@v4", "actions/upload-artifact@v4",
        ])
        install = self.one("name", "Install baseline host dependencies")
        self.assertEqual(install["if"], (
            "steps.toolchain.outputs.cache-matched-key != '' && steps.dependencies.outputs.cache-matched-key != ''", []))
        self.assertEqual(install["timeout-minutes"], ("15", []))
        for step in self.steps:
            if "run" in step:
                self.assertNotRegex(script(step), r"toolchain_install|(?:curl|wget)\s|make\s.*third_party|git clone")

    def test_pinned_python_and_initial_receipt_precede_caches_and_execution(self):
        provision = self.one("uses", "actions/setup-python@v5")
        self.assertEqual(scalars(children(provision, "with", 10)), {
            "python-version": "'3.12.14'", "architecture": "x64", "check-latest": "false",
        })
        required_order = [
            self.one("uses", "actions/checkout@v4"), self.one("name", INITIALIZE), provision,
            self.one("name", INTERPRETER), self.one("id", "pins"), self.one("id", "toolchain"),
            self.one("id", "dependencies"), self.one("name", "Install baseline host dependencies"),
            self.one("name", PREPARE), self.one("name", EXECUTE), self.one("uses", "actions/upload-artifact@v4"),
        ]
        self.assertEqual(self.steps, required_order)
        python_body(self.one("name", INTERPRETER), isolated=True)

    def test_actual_resource_guard_retains_failed_job_and_accepts_exact_limits(self):
        body = python_body(self.one("name", INITIALIZE))
        for disk, memory, accepted in (
            (15 * 1024**3, 4 * 1024**3, True),
            (15 * 1024**3 - 1, 4 * 1024**3, False),
            (15 * 1024**3, 4 * 1024**3 - 1, False),
            (15 * 1024**3, 0, False), (15 * 1024**3, None, False),
        ):
            with self.subTest(disk=disk, memory=memory), tempfile.TemporaryDirectory(prefix="managed-ci-resource-") as temporary:
                root = Path(temporary)
                setup = ("import shutil, sys\nfrom types import SimpleNamespace\n"
                         f"sys.path.insert(0, {str(ROOT / 'ci/project')!r})\nimport preflight\n"
                         f"shutil.disk_usage = lambda path: SimpleNamespace(free={disk!r})\n"
                         f"preflight.available_memory_bytes = lambda: {memory!r}\n"
                         f"exec(compile({body!r}, 'workflow-initialization', 'exec'))\n")
                result = subprocess.run([sys.executable, "-c", setup], cwd=ROOT,
                                        env=host_environment(root), capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode == 0, accepted, result.stderr)
                evidence = root / "p06-managed-preflight/evidence"
                receipt = json.loads((evidence / "job.json").read_text())
                self.assertEqual(receipt["free_disk_bytes_before_cache"], disk)
                self.assertEqual(receipt["available_memory_bytes_before_cache"], memory)
                self.assertEqual(receipt["native_execution"], "not_run")
                self.assertIs(receipt["native_preflight_passed"], False)
                for name in CLAIMS:
                    self.assertIs(receipt[name], False)
                self.assertEqual((receipt["requested_processes"], receipt["requested_launches"],
                                  receipt["requested_checked_words"]), (4, 132, 4224))
                self.assertEqual((evidence / "workflow.yml").read_bytes(), WORKFLOW.read_bytes())
                self.assertEqual(receipt["workflow_sha256"], hashlib.sha256(WORKFLOW.read_bytes()).hexdigest())
                self.assertEqual((root / "environment").read_text(),
                                 "P06_PREFLIGHT_ROOT=" + str(root / "p06-managed-preflight") + "\n")
                if not accepted:
                    self.assertIn("15 GiB disk reserve and 4 GiB available memory", result.stderr)

    def test_actual_interpreter_check_rejects_version_platform_and_path_mismatches(self):
        body = python_body(self.one("name", INTERPRETER), isolated=True)
        executable = str(Path(sys.executable).resolve())
        observations = [
            ((3, 12, 14), "CPython", "linux", executable, True),
            ((3, 12, 13), "CPython", "linux", executable, False),
            ((3, 12, 14), "PyPy", "linux", executable, False),
            ((3, 12, 14), "CPython", "darwin", executable, False),
            ((3, 12, 14), "CPython", "linux", None, False),
            ((3, 12, 14), "CPython", "linux", "/different/python3", False),
        ]
        for version, implementation, platform_name, selected, accepted in observations:
            with self.subTest(version=version, platform=platform_name, selected=selected), tempfile.TemporaryDirectory(prefix="managed-ci-python-") as temporary:
                root = Path(temporary)
                (root / "evidence").mkdir()
                setup = ("import platform, shutil, sys\nfrom pathlib import Path\n"
                         f"sys.version_info = {version!r}\n"
                         f"sys.executable = {executable!r}\nsys.platform = {platform_name!r}\n"
                         f"platform.python_implementation = lambda: {implementation!r}\n"
                         f"shutil.which = lambda name: {selected!r}\n"
                         f"exec(compile({body!r}, 'workflow-python-identity', 'exec'))\n")
                environment = dict(host_environment(root), P06_PREFLIGHT_ROOT=str(root))
                result = subprocess.run([sys.executable, "-c", setup], cwd=ROOT, env=environment,
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode == 0, accepted, result.stderr)
                receipt = json.loads((root / "evidence/python-provision.json").read_text())
                self.assertEqual(receipt["python_version"], list(version))
                self.assertEqual(receipt["implementation"], implementation)
                self.assertEqual(receipt["platform"], platform_name)
                self.assertEqual(receipt["python3_on_path"], selected)
                if not accepted:
                    self.assertIn("Python interpreter identity differs", result.stderr)

    def test_preparation_binds_revision_both_formats_and_matched_cache_keys(self):
        prepare = self.one("name", PREPARE)
        argv = one_command(prepare, pipefail=True)
        self.assertEqual(argv[:2], ["python3", "ci/project/p04_ci_prepare.py"])
        for option, value in (("--source-dir", "$PWD"), ("--workspace-dir", "$P06_PREFLIGHT_ROOT"),
                              ("--expected-revision", "$GITHUB_SHA"), ("--backend", "simx"), ("--format", "both")):
            self.assertEqual(argv[argv.index(option) + 1], value)
        environment = scalars(children(prepare, "env", 10))
        self.assertEqual(environment["P06_PREFLIGHT_TOOLCHAIN_CACHE"], "${{ steps.toolchain.outputs.cache-matched-key }}")
        self.assertEqual(environment["P06_PREFLIGHT_DEPENDENCY_CACHE"], "${{ steps.dependencies.outputs.cache-matched-key }}")
        for option, value in (("--toolchain-id", "$P06_PREFLIGHT_TOOLCHAIN_ID"),
                              ("--toolchain-cache-key", "$P06_PREFLIGHT_TOOLCHAIN_CACHE"),
                              ("--third-party-cache-key", "$P06_PREFLIGHT_DEPENDENCY_CACHE"),
                              ("--expected-third-party-key", "$P06_PREFLIGHT_DEPENDENCY_KEY")):
            self.assertEqual(argv[argv.index(option) + 1], value)

    def test_actual_execution_command_is_accepted_by_current_runner_cli(self):
        execute = self.one("name", EXECUTE)
        self.assertEqual(set(execute), {"name", "run"})
        argv = one_command(execute, pipefail=True)
        self.assertEqual(argv[:3], ["python3", "ci/project/p06_managed_preflight_execute.py", "run"])
        invocation = argv[2:argv.index("2>&1")]
        args = runner.argument_parser().parse_args(invocation)
        self.assertEqual(args.mode, "run")
        self.assertEqual((args.jobs, args.timeout_seconds, args.run_timeout_seconds), (2, 1800, 180))
        self.assertEqual(args.expected_revision, "$GITHUB_SHA")
        self.assertEqual(args.source_dir, Path("$PWD"))
        self.assertEqual(args.output, Path("$P06_PREFLIGHT_ROOT/evidence/managed-preflight"))
        self.assertEqual(args.tools_dir, Path("$P06_PREFLIGHT_ROOT/tools"))
        self.assertEqual(args.work_dir, Path("$P06_PREFLIGHT_ROOT/work"))
        self.assertIsNone(args.host_bin)
        self.assertEqual(argv[argv.index("2>&1"):],
                         ["2>&1", "|", "tee", "$P06_PREFLIGHT_ROOT/evidence/execution.log"])
        for option in ("--backend", "--format", "--policy", "--samples", "--pairs", "--iterations",
                       "--threshold", "--outlier", "--development", "--warm"):
            with self.subTest(option=option), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                runner.argument_parser().parse_args([*invocation, option, "1"])
            self.assertEqual(error.exception.code, 2)

    def test_historical_full_warm_path_remains_separate_and_complete(self):
        historical = workflow(ROOT / ".github/workflows/p06-warm-workspace.yml")
        job = children(children(historical, "jobs", 2), "experiment", 4)
        execute = self.one("name", "Execute all warm workspace pairs serially", steps(job))
        argv = one_command(execute, pipefail=True)
        self.assertEqual(argv[:3], ["python3", "ci/project/p06_warm_execute.py", "run"])
        self.assertNotIn("p06_managed_preflight_execute.py", script(execute))
        self.assertEqual(len(warm.process_plan(warm.load_contract())), 24)
        self.assertEqual(len(contract.process_plan(contract.load_contract())), 4)
        for option in ("--pairs", "--samples", "--iterations", "--preflight"):
            self.assertNotIn(option, argv)

    def test_actual_failed_shell_pipelines_keep_both_streams_and_producer_status(self):
        for name, log_name, executable in (
            (PREPARE, "preparation.log", "python3"),
            (EXECUTE, "execution.log", "python3"),
            ("Install baseline host dependencies", "host-dependencies.log", "sudo"),
        ):
            with self.subTest(step=name), tempfile.TemporaryDirectory(prefix="managed-ci-pipeline-") as temporary:
                root = Path(temporary)
                (root / "evidence").mkdir()
                stub = root / executable
                stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$P06_CI_ARGUMENTS"\n'
                                'printf "synthetic producer failed\\n"\n'
                                'printf "synthetic stderr\\n" >&2\nexit 37\n')
                stub.chmod(0o700)
                environment = dict(host_environment(root),
                    PATH=str(root) + os.pathsep + os.defpath, P06_PREFLIGHT_ROOT=str(root),
                    P06_CI_ARGUMENTS=str(root / "arguments"),
                    **{key: "synthetic-unused" for key in ("P06_PREFLIGHT_TOOLCHAIN_ID",
                       "P06_PREFLIGHT_TOOLCHAIN_CACHE", "P06_PREFLIGHT_DEPENDENCY_CACHE", "P06_PREFLIGHT_DEPENDENCY_KEY")})
                result = subprocess.run(["/bin/bash", "-c", script(self.one("name", name))],
                                        cwd=ROOT, env=environment, text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 37, result.stderr)
                self.assertEqual((root / "evidence" / log_name).read_text(),
                                 "synthetic producer failed\nsynthetic stderr\n")
                self.assertTrue((root / "arguments").read_text())

    def test_all_run_scripts_and_embedded_python_are_syntax_valid(self):
        for step in self.steps:
            if "run" in step:
                with self.subTest(step=step.get("name")):
                    result = subprocess.run(["/bin/bash", "-n"], input=script(step),
                                            text=True, capture_output=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    if "<<'PY'" in script(step):
                        compile(python_body(step, isolated=step == self.one("name", INTERPRETER)),
                                str(WORKFLOW), "exec")

    def test_failure_artifacts_cover_the_whole_attempt_with_unique_identity(self):
        upload = self.one("uses", "actions/upload-artifact@v4")
        self.assertEqual(upload["if"], ("always()", []))
        config = scalars(children(upload, "with", 10))
        self.assertEqual(config["path"], "${{ runner.temp }}/p06-managed-preflight/evidence")
        self.assertEqual(config["name"],
                         "p06-managed-preflight-${{ github.sha }}-run${{ github.run_id }}-attempt${{ github.run_attempt }}")
        self.assertEqual(config["if-no-files-found"], "error")
        self.assertEqual(config["retention-days"], "30")
        self.assertEqual(config["include-hidden-files"], "true")
        self.assertEqual(config["compression-level"], "6")
        self.assertEqual(self.steps[-1], upload)


if __name__ == "__main__":
    unittest.main()
