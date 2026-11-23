# SPDX-License-Identifier: Apache-2.0
"""Host checks for native lifetime workflow limits and retained failure evidence."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import p04_ci_prepare
import p06_managed_preflight_execute as preflight
import p06_native_lifetime_contract as contract
import p06_native_lifetime_execute as runner
import p06_pending_probe as probe
from test_p05_ci_workflow import children, path_filters, scalars, script, steps, workflow
from test_p06_managed_preflight_ci import host_environment, python_body, required_sources
from test_p06_workspace_ci import covers, one_command


ROOT = preflight.ROOT
WORKFLOW = ROOT / ".github/workflows/p06-native-lifetime.yml"
INITIALIZE = "Initialize retained job identity and resource observations"
INTERPRETER = "Retain and verify Python interpreter identity"
PREPARE = "Verify clean source and relocate restored tools"
EXECUTE = "Execute all managed lifetime processes serially"
PROBE = "Observe native pending reads and reject the always-zero control"


class NativeLifetimeWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = workflow(WORKFLOW)
        cls.events = children(cls.workflow, "on", 2)
        cls.jobs = children(cls.workflow, "jobs", 2)
        cls.job = children(cls.jobs, "native-lifetime", 4)
        cls.steps = steps(cls.job)

    def one(self, key, value):
        found = [step for step in self.steps if step.get(key, (None,))[0] == value]
        self.assertEqual(len(found), 1, (key, value))
        return found[0]

    def test_triggers_cover_managed_sources_new_helpers_probe_and_docs(self):
        self.assertEqual(set(self.events), {"push", "pull_request", "workflow_dispatch"})
        self.assertEqual(self.events["workflow_dispatch"], ("", []))
        self.assertEqual(children(self.events, "push", 4)["branches"], ("[master]", []))
        self.assertEqual(path_filters(self.events, "push"), path_filters(self.events, "pull_request"))
        names = required_sources() | set(contract.SOURCE_FILES) | set(probe.SOURCE_FILES)
        names.update(path.relative_to(ROOT).as_posix()
                     for path in (ROOT / "ci/project").glob("*native_lifetime*.py"))
        names.update(path.relative_to(ROOT).as_posix()
                     for path in (ROOT / "tests/unittest/pending_reads").iterdir() if path.is_file())
        self.assertIn("docs/designs/managed_counter_lifetime_v1.md", names)
        self.assertIn("ci/project/p06_pending_probe.py", names)
        for event in ("push", "pull_request"):
            with self.subTest(event=event):
                patterns = path_filters(self.events, event)
                self.assertEqual(sorted(name for name in names if not covers(patterns, name)), [])

    def test_governance_covers_new_contract_probe_and_tests(self):
        events = children(workflow(ROOT / ".github/workflows/project-governance.yml"), "on", 2)
        names = set(contract.SOURCE_FILES) | set(probe.SOURCE_FILES)
        names.update(path.relative_to(ROOT).as_posix()
                     for path in (ROOT / "ci/project").glob("*native_lifetime*.py"))
        for event in ("push", "pull_request"):
            patterns = path_filters(events, event)
            self.assertEqual(sorted(name for name in names if not covers(patterns, name)), [], event)

    def test_single_hosted_worker_and_resource_budget_are_fixed(self):
        self.assertEqual(set(self.jobs), {"native-lifetime"})
        self.assertEqual(self.job["runs-on"], ("ubuntu-22.04", []))
        self.assertEqual(self.job["timeout-minutes"], ("90", []))
        self.assertNotIn("strategy", self.job)
        self.assertNotRegex(WORKFLOW.read_text(), r"matrix\.|max-parallel|self-hosted")
        self.assertEqual(preflight.BUDGET, {"min_free_bytes": 15 * 1024**3,
            "max_rss_bytes": 4 * 1024**3, "max_log_bytes": 16 * 1024**2})
        self.assertEqual((p04_ci_prepare.MIN_FREE_BYTES, p04_ci_prepare.MAX_RSS_BYTES),
                         (15 * 1024**3, 4 * 1024**3))
        self.assertEqual(scalars(children(self.job, "env", 6)), {
            "PYTHONDONTWRITEBYTECODE": "'1'", "MAKEFLAGS": "'-j2'", "THREADS": "'1'",
            "CMAKE_BUILD_PARALLEL_LEVEL": "'2'", "CCACHE_DISABLE": "'1'", "OBJCACHE": "''",
        })
        environment = preflight.clean_environment({"host_bin": None, "work": Path("/unused")}, 2)
        self.assertEqual((environment["THREADS"], environment["MAKEFLAGS"],
                          environment["CMAKE_BUILD_PARALLEL_LEVEL"]), ("1", "-j2", "2"))
        for step in self.steps:
            if "env" in step:
                self.assertNotIn("THREADS", children(step, "env", 10))

    def test_read_only_workflow_has_no_secrets_failure_suppression_or_cache_writes(self):
        self.assertEqual(scalars(children(self.workflow, "permissions", 2)), {"contents": "read"})
        self.assertEqual(scalars(children(self.workflow, "concurrency", 2)), {
            "group": "p06-native-lifetime-${{ github.event_name }}-${{ github.ref }}",
            "cancel-in-progress": "false",
        })
        self.assertEqual(scalars(children(self.one("uses", "actions/checkout@v4"), "with", 10)), {
            "fetch-depth": "1", "submodules": "recursive", "persist-credentials": "false",
        })
        cache_steps = [step for step in self.steps if step.get("uses", ("",))[0].startswith("actions/cache")]
        self.assertEqual(len(cache_steps), 2)
        for step in cache_steps:
            self.assertEqual(step["uses"], ("actions/cache/restore@v4", []))
        self.assertNotRegex(WORKFLOW.read_text(),
            r"secrets\s*\.|pull_request_target|workflow_run|write-all|id-token:|continue-on-error")
        for step in self.steps:
            self.assertTrue(set(step) <= {"name", "uses", "with", "run", "id", "if", "env", "timeout-minutes"})
            if "if" in step:
                self.assertIn(step, [self.one("name", "Install baseline host dependencies"),
                                     self.one("uses", "actions/upload-artifact@v4")])
            if "run" in step:
                self.assertNotRegex(script(step), r"\|\|\s*true|set\s+\+|(?:^|\s)exit\s+0|git\s+push|gh\s+")

    def test_actual_resource_guard_retains_failed_receipts_and_accepts_exact_limits(self):
        body = python_body(self.one("name", INITIALIZE))
        for disk, memory, accepted in (
            (15 * 1024**3, 4 * 1024**3, True),
            (15 * 1024**3 - 1, 4 * 1024**3, False),
            (15 * 1024**3, 4 * 1024**3 - 1, False),
            (15 * 1024**3, 0, False), (15 * 1024**3, None, False),
        ):
            with self.subTest(disk=disk, memory=memory), tempfile.TemporaryDirectory(prefix="lifetime-ci-resource-") as temporary:
                root = Path(temporary)
                setup = ("import shutil, sys\nfrom types import SimpleNamespace\n"
                         f"sys.path.insert(0, {str(ROOT / 'ci/project')!r})\nimport preflight\n"
                         f"shutil.disk_usage = lambda path: SimpleNamespace(free={disk!r})\n"
                         f"preflight.available_memory_bytes = lambda: {memory!r}\n"
                         f"exec(compile({body!r}, 'workflow-initialization', 'exec'))\n")
                environment = dict(host_environment(root), GITHUB_JOB="native-lifetime")
                result = subprocess.run([sys.executable, "-c", setup], cwd=ROOT,
                    env=environment, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode == 0, accepted, result.stderr)
                evidence = root / "p06-native-lifetime/evidence"
                receipt = json.loads((evidence / "job.json").read_text())
                self.assertEqual(receipt["contract_id"], contract.CONTRACT_ID)
                self.assertEqual(receipt["scope"], contract.SCOPE)
                self.assertEqual(receipt["free_disk_bytes_before_cache"], disk)
                self.assertEqual(receipt["available_memory_bytes_before_cache"], memory)
                self.assertEqual(receipt["native_execution"], "not_run")
                for flag in (*contract.FALSE_CLAIMS, "native_preflight_passed", "native_lifetime_passed"):
                    self.assertIs(receipt[flag], False)
                self.assertEqual((receipt["requested_processes"], receipt["requested_launches"],
                                  receipt["requested_checked_words"]), (4, 132, 4224))
                self.assertEqual((receipt["requested_build_jobs"], receipt["requested_simulation_workers"]), (2, 1))
                self.assertEqual((evidence / "workflow.yml").read_bytes(), WORKFLOW.read_bytes())
                self.assertEqual(receipt["workflow_sha256"], hashlib.sha256(WORKFLOW.read_bytes()).hexdigest())
                self.assertEqual((root / "environment").read_text(),
                                 "P06_LIFETIME_ROOT=" + str(root / "p06-native-lifetime") + "\n")
                if not accepted:
                    self.assertIn("15 GiB disk reserve and 4 GiB available memory", result.stderr)

    def test_pinned_python_identity_is_checked_before_cache_restoration(self):
        provision = self.one("uses", "actions/setup-python@v5")
        self.assertEqual(scalars(children(provision, "with", 10)), {
            "python-version": "'3.12.14'", "architecture": "x64", "check-latest": "false",
        })
        ordered = [self.one("uses", "actions/checkout@v4"), self.one("name", INITIALIZE), provision,
                   self.one("name", INTERPRETER), self.one("id", "toolchain"),
                   self.one("id", "dependencies"), self.one("name", PREPARE)]
        self.assertEqual([self.steps.index(step) for step in ordered],
                         sorted(self.steps.index(step) for step in ordered))
        body = python_body(self.one("name", INTERPRETER), isolated=True)
        executable = str(Path(sys.executable).resolve())
        for version, selected, accepted in (((3, 12, 14), executable, True),
                                           ((3, 12, 13), executable, False),
                                           ((3, 12, 14), None, False)):
            with self.subTest(version=version, selected=selected), tempfile.TemporaryDirectory(prefix="lifetime-ci-python-") as temporary:
                root = Path(temporary)
                (root / "evidence").mkdir()
                setup = ("import platform, shutil, sys\n"
                         f"sys.version_info = {version!r}\nsys.executable = {executable!r}\n"
                         "sys.platform = 'linux'\nplatform.python_implementation = lambda: 'CPython'\n"
                         f"shutil.which = lambda name: {selected!r}\n"
                         f"exec(compile({body!r}, 'workflow-python-identity', 'exec'))\n")
                environment = dict(host_environment(root), P06_LIFETIME_ROOT=str(root))
                result = subprocess.run([sys.executable, "-c", setup], cwd=ROOT, env=environment,
                    capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode == 0, accepted, result.stderr)
                receipt = json.loads((root / "evidence/python-provision.json").read_text())
                self.assertEqual(receipt["python_version"], list(version))
                self.assertEqual(receipt["python3_on_path"], selected)
                if not accepted:
                    self.assertIn("Python interpreter identity differs", result.stderr)

    def test_preparation_requires_both_pinned_restored_inputs_and_revision(self):
        prepare = self.one("name", PREPARE)
        argv = one_command(prepare, pipefail=True)
        self.assertEqual(argv[:2], ["python3", "ci/project/p04_ci_prepare.py"])
        for option, value in (("--source-dir", "$PWD"), ("--workspace-dir", "$P06_LIFETIME_ROOT"),
                             ("--expected-revision", "$GITHUB_SHA"), ("--backend", "simx"), ("--format", "both"),
                             ("--toolchain-id", "$P06_LIFETIME_TOOLCHAIN_ID"),
                             ("--toolchain-cache-key", "$P06_LIFETIME_TOOLCHAIN_CACHE"),
                             ("--third-party-cache-key", "$P06_LIFETIME_DEPENDENCY_CACHE"),
                             ("--expected-third-party-key", "$P06_LIFETIME_DEPENDENCY_KEY")):
            self.assertEqual(argv[argv.index(option) + 1], value)
        environment = scalars(children(prepare, "env", 10))
        self.assertEqual(environment["P06_LIFETIME_TOOLCHAIN_CACHE"], "${{ steps.toolchain.outputs.cache-matched-key }}")
        self.assertEqual(environment["P06_LIFETIME_DEPENDENCY_CACHE"], "${{ steps.dependencies.outputs.cache-matched-key }}")
        self.assertEqual(self.one("name", "Install baseline host dependencies")["if"], (
            "steps.toolchain.outputs.cache-matched-key != '' && steps.dependencies.outputs.cache-matched-key != ''", []))

    def test_actual_managed_and_probe_invocations_use_matching_paths_and_run_serially(self):
        execute, pending = self.one("name", EXECUTE), self.one("name", PROBE)
        self.assertNotIn("if", execute)
        self.assertNotIn("if", pending)
        self.assertLess(self.steps.index(self.one("name", PREPARE)), self.steps.index(execute))
        self.assertLess(self.steps.index(execute), self.steps.index(pending))
        argv = one_command(execute, pipefail=True)
        self.assertEqual(argv[:3], ["python3", "ci/project/p06_native_lifetime_execute.py", "run"])
        args = runner.argument_parser().parse_args(argv[2:argv.index("2>&1")])
        self.assertEqual((args.mode, args.jobs, args.timeout_seconds, args.run_timeout_seconds), ("run", 2, 1800, 180))
        self.assertEqual(args.expected_revision, "$GITHUB_SHA")
        self.assertEqual(args.source_dir, Path("$PWD"))
        self.assertEqual(args.output, Path("$P06_LIFETIME_ROOT/evidence/native-lifetime"))
        self.assertEqual(args.tools_dir, Path("$P06_LIFETIME_ROOT/tools"))
        self.assertEqual(args.work_dir, Path("$P06_LIFETIME_ROOT/work"))
        self.assertIsNone(args.host_bin)
        pending_argv = one_command(pending, pipefail=True)
        self.assertEqual(pending_argv[:2], ["python3", "ci/project/p06_pending_probe.py"])
        pending_args = probe.argument_parser().parse_args(pending_argv[2:pending_argv.index("2>&1")])
        self.assertEqual(pending_args.source_dir, args.source_dir)
        self.assertEqual(pending_args.expected_revision, args.expected_revision)
        self.assertEqual(pending_args.build_dir, args.work_dir / "simx-fp16")
        self.assertEqual(pending_args.managed_report, args.output / "report.json")
        self.assertEqual(pending_args.output_dir, Path("$P06_LIFETIME_ROOT/evidence/pending-probe"))
        self.assertIsNone(pending_args.host_bin)

    def test_actual_failed_pipelines_retain_stdout_stderr_and_producer_status(self):
        for name, log_name, executable in (
            (PREPARE, "preparation.log", "python3"), (EXECUTE, "execution.log", "python3"),
            (PROBE, "pending-probe.log", "python3"),
            ("Install baseline host dependencies", "host-dependencies.log", "sudo"),
        ):
            with self.subTest(step=name), tempfile.TemporaryDirectory(prefix="lifetime-ci-pipeline-") as temporary:
                root = Path(temporary)
                (root / "evidence").mkdir()
                stub = root / executable
                stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$P06_CI_ARGUMENTS"\n'
                                'printf "synthetic producer failed\\n"\n'
                                'printf "synthetic stderr\\n" >&2\nexit 37\n')
                stub.chmod(0o700)
                environment = dict(host_environment(root),
                    PATH=str(root) + os.pathsep + os.defpath, P06_LIFETIME_ROOT=str(root),
                    P06_CI_ARGUMENTS=str(root / "arguments"),
                    **{key: "synthetic-unused" for key in ("P06_LIFETIME_TOOLCHAIN_ID",
                       "P06_LIFETIME_TOOLCHAIN_CACHE", "P06_LIFETIME_DEPENDENCY_CACHE", "P06_LIFETIME_DEPENDENCY_KEY")})
                result = subprocess.run(["/bin/bash", "-c", script(self.one("name", name))],
                    cwd=ROOT, env=environment, text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 37, result.stderr)
                self.assertEqual((root / "evidence" / log_name).read_text(),
                                 "synthetic producer failed\nsynthetic stderr\n")
                self.assertTrue((root / "arguments").read_text())

    def test_shell_scripts_and_embedded_python_compile(self):
        for step in self.steps:
            if "run" in step:
                with self.subTest(step=step.get("name")):
                    result = subprocess.run(["/bin/bash", "-n"], input=script(step),
                        text=True, capture_output=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    if "<<'PY'" in script(step):
                        compile(python_body(step, isolated=step == self.one("name", INTERPRETER)),
                                str(WORKFLOW), "exec")

    def test_failure_artifacts_always_include_managed_and_probe_evidence(self):
        upload = self.one("uses", "actions/upload-artifact@v4")
        self.assertEqual(upload["if"], ("always()", []))
        config = scalars(children(upload, "with", 10))
        self.assertEqual(config["path"], "${{ runner.temp }}/p06-native-lifetime/evidence")
        self.assertEqual(config["name"],
                         "p06-native-lifetime-${{ github.sha }}-run${{ github.run_id }}-attempt${{ github.run_attempt }}")
        self.assertEqual(config["if-no-files-found"], "error")
        self.assertEqual(config["retention-days"], "30")
        self.assertEqual(config["include-hidden-files"], "true")
        self.assertEqual(self.steps[-1], upload)


if __name__ == "__main__":
    unittest.main()
