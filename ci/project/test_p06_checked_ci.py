# SPDX-License-Identifier: Apache-2.0
"""Host-only checks of checked-counter workflow trust and failure retention."""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import p04_ci_prepare
import p06_checked_execute as runner
import preflight
from test_p05_ci_workflow import children, path_filters, scalars, script, steps, workflow
from test_p06_workspace_ci import covers, one_command


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/p06-checked-counters.yml"
IDENTITY = "Initialize retained job identity and resource observations"
PYTHON_IDENTITY = "Retain and verify Python interpreter identity"
PREPARE = "Verify clean source and relocate restored tools"
EXECUTE = "Execute ordinary and checked native prerequisites"
GIB = 1024**3


def python_body(step, invocation):
    lines = script(step).splitlines()
    if lines[:2] != ["set -euo pipefail", invocation] or lines[-1] != "PY":
        raise AssertionError("expected one Python heredoc under shell error propagation")
    return "\n".join(lines[2:-1])


def required_sources():
    tracked = subprocess.check_output([
        "git", "ls-files", "-z", "--", "sim", "sw/common", "third_party/ramulator_ext",
    ], cwd=ROOT, text=True, timeout=5)
    return set(filter(None, tracked.split("\0"))) | set(runner.CRITICAL + runner.COPIED) | {
        WORKFLOW.relative_to(ROOT).as_posix(), Path(__file__).relative_to(ROOT).as_posix(),
        ".github/workflows/p04-model.yml", "ci/toolchain_rev.sh", "ci/install_dependencies.sh",
        "ci/project/p04_ci_prepare.py", "Makefile.in", "third_party/Makefile",
        "docs/designs/simx_checked_counters_v1.md", "docs/designs/simulator_completion_v1.md",
    }


class CheckedCounterWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = workflow(WORKFLOW)
        cls.events = children(cls.workflow, "on", 2)
        cls.jobs = children(cls.workflow, "jobs", 2)
        cls.job = children(cls.jobs, "native-counters", 4)
        cls.steps = steps(cls.job)

    def one(self, key, value):
        found = [step for step in self.steps if step.get(key, (None,))[0] == value]
        self.assertEqual(len(found), 1, (key, value))
        return found[0]

    def test_master_push_pull_request_and_manual_dispatch_have_symmetric_filters(self):
        self.assertEqual(set(self.workflow), {"name", "on", "permissions", "concurrency", "jobs"})
        self.assertEqual(set(self.events), {"push", "pull_request", "workflow_dispatch"})
        self.assertEqual(self.events["workflow_dispatch"], ("", []))
        self.assertEqual(children(self.events, "push", 4)["branches"], ("[master]", []))
        self.assertEqual(set(children(self.events, "push", 4)), {"branches", "paths"})
        self.assertEqual(set(children(self.events, "pull_request", 4)), {"paths"})
        self.assertEqual(path_filters(self.events, "push"), path_filters(self.events, "pull_request"))

    def test_retained_native_and_preparation_inputs_trigger_both_events(self):
        for event in ("push", "pull_request"):
            patterns = path_filters(self.events, event)
            self.assertEqual(sorted(name for name in required_sources() if not covers(patterns, name)), [],
                             event + " omits a retained source or preparation input")

    def test_missing_guard_harness_completion_and_helper_filters_are_detectable(self):
        patterns = path_filters(self.events, "push")
        witnesses = {
            "sim/**": "sim/common/perf_counter.h",
            "tests/unittest/checked_counters/**": "tests/unittest/checked_counters/main.cpp",
            "sw/runtime/common/async_run.h": "sw/runtime/common/async_run.h",
            "ci/project/**": "ci/project/p06_checked_execute.py",
            "ci/blackbox.sh": "ci/blackbox.sh",
        }
        for pattern, source in witnesses.items():
            with self.subTest(source=source):
                self.assertTrue(covers(patterns, source))
                self.assertFalse(covers(patterns - {pattern}, source))

    def test_changed_counter_contract_and_tests_also_trigger_host_governance(self):
        events = children(workflow(ROOT / ".github/workflows/project-governance.yml"), "on", 2)
        sources = {
            WORKFLOW.relative_to(ROOT).as_posix(), Path(__file__).relative_to(ROOT).as_posix(),
            "ci/project/p06_checked_execute.py", "ci/project/fixtures/p06_checked_counter_test.cpp",
            "tests/unittest/checked_counters/main.cpp", "sim/common/perf_counter.h",
            "sim/simx/types.h", "sim/simx/checked_counters.mk", "sw/runtime/common/async_run.h",
            "docs/designs/simx_checked_counters_v1.md",
        }
        for event in ("push", "pull_request"):
            patterns = path_filters(events, event)
            self.assertEqual(sorted(source for source in sources if not covers(patterns, source)), [])

    def test_hosted_serial_job_preserves_native_resource_limits(self):
        self.assertEqual(set(self.jobs), {"native-counters"})
        self.assertEqual(set(self.job), {"name", "runs-on", "timeout-minutes", "defaults", "env", "steps"})
        self.assertEqual(self.job["runs-on"], ("ubuntu-22.04", []))
        self.assertEqual(self.job["timeout-minutes"], ("90", []))
        defaults = children(self.job, "defaults", 6)
        self.assertEqual(set(defaults), {"run"})
        self.assertEqual(scalars(children(defaults, "run", 8)), {"shell": "bash"})
        self.assertEqual(scalars(children(self.job, "env", 6)), {
            "PYTHONDONTWRITEBYTECODE": "'1'", "MAKEFLAGS": "'-j2'", "THREADS": "'1'",
            "CMAKE_BUILD_PARALLEL_LEVEL": "'2'", "CCACHE_DISABLE": "'1'", "OBJCACHE": "''",
        })
        self.assertEqual(runner.BUDGET, {"min_free_bytes": 15 * GIB, "max_rss_bytes": 4 * GIB,
                                       "max_log_bytes": 16 * 1024**2})
        self.assertEqual(runner.TIMEOUTS, {"configure": 120, "build": 1800, "run": 180})
        self.assertEqual((p04_ci_prepare.MIN_FREE_BYTES, p04_ci_prepare.MAX_RSS_BYTES),
                         (15 * GIB, 4 * GIB))

    def test_read_only_checkout_and_actions_cannot_suppress_failures_or_write_cache(self):
        self.assertEqual(scalars(children(self.workflow, "permissions", 2)), {"contents": "read"})
        self.assertEqual(scalars(children(self.workflow, "concurrency", 2)), {
            "group": "p06-checked-counters-${{ github.event_name }}-${{ github.ref }}",
            "cancel-in-progress": "false",
        })
        self.assertEqual(scalars(children(self.one("uses", "actions/checkout@v4"), "with", 10)), {
            "fetch-depth": "1", "submodules": "recursive", "persist-credentials": "false",
        })
        self.assertEqual([step["uses"][0] for step in self.steps if "uses" in step], [
            "actions/checkout@v4", "actions/setup-python@v5", "actions/cache/restore@v4",
            "actions/cache/restore@v4", "actions/upload-artifact@v4",
        ])
        for step in self.steps:
            self.assertTrue(set(step) <= {"name", "uses", "with", "run", "id", "if", "env", "timeout-minutes"})
            if "if" in step:
                self.assertIn(step, [self.one("name", "Install baseline host dependencies"),
                                     self.one("uses", "actions/upload-artifact@v4")])
            if "run" in step:
                self.assertNotRegex(script(step), r"\|\|\s*true|set\s+\+|(?:^|\s)exit\s+0|git\s+push|gh\s+")
        self.assertNotRegex(WORKFLOW.read_text(),
            r"secrets\s*(?:\.|\[)|pull_request_target|workflow_run|self-hosted|write-all|id-token:|continue-on-error")

    def test_matching_restore_only_cache_receipts_are_required_before_native_execution(self):
        self.assertEqual(scalars(children(self.one("id", "toolchain"), "with", 10)), {
            "path": "tools", "key": "${{ runner.os }}-toolchain-${{ steps.pins.outputs.toolchain }}-lite",
            "restore-keys": "${{ runner.os }}-toolchain-${{ steps.pins.outputs.toolchain }}-",
        })
        self.assertEqual(scalars(children(self.one("id", "dependencies"), "with", 10)), {
            "path": "third_party", "key": "${{ runner.os }}-thirdparty-${{ hashFiles('third_party/Makefile', '.gitmodules') }}",
        })
        pins = script(self.one("id", "pins"))
        self.assertIn("$(bash ci/toolchain_rev.sh)", pins)
        self.assertIn("[0-9a-f]{40}", pins)
        self.assertIn('>> "$GITHUB_OUTPUT"', pins)
        install = self.one("name", "Install baseline host dependencies")
        self.assertEqual(install["if"], (
            "steps.toolchain.outputs.cache-matched-key != '' && steps.dependencies.outputs.cache-matched-key != ''", []))
        self.assertEqual(install["timeout-minutes"], ("15", []))
        for step in self.steps:
            if "run" in step:
                self.assertNotRegex(script(step), r"toolchain_install|(?:curl|wget)\s|make\s.*third_party|git clone")
        ordered = [self.one("uses", "actions/checkout@v4"), self.one("name", IDENTITY),
                   self.one("uses", "actions/setup-python@v5"), self.one("name", PYTHON_IDENTITY),
                   self.one("id", "pins"), self.one("id", "toolchain"), self.one("id", "dependencies"),
                   install, self.one("name", PREPARE), self.one("name", EXECUTE),
                   self.one("uses", "actions/upload-artifact@v4")]
        self.assertEqual([self.steps.index(step) for step in ordered],
                         sorted(self.steps.index(step) for step in ordered))

    def test_preparation_binds_checkout_revision_and_actual_cache_match_keys(self):
        prepare = self.one("name", PREPARE)
        self.assertEqual(set(prepare), {"name", "env", "run"})
        self.assertEqual(scalars(children(prepare, "env", 10)), {
            "P06_CHECKED_TOOLCHAIN_ID": "${{ steps.pins.outputs.toolchain }}",
            "P06_CHECKED_TOOLCHAIN_CACHE": "${{ steps.toolchain.outputs.cache-matched-key }}",
            "P06_CHECKED_DEPENDENCY_CACHE": "${{ steps.dependencies.outputs.cache-matched-key }}",
            "P06_CHECKED_DEPENDENCY_KEY": "${{ runner.os }}-thirdparty-${{ hashFiles('third_party/Makefile', '.gitmodules') }}",
        })
        self.assertEqual(one_command(prepare, pipefail=True), [
            "python3", "ci/project/p04_ci_prepare.py", "--source-dir", "$PWD", "--workspace-dir", "$P06_CHECKED_ROOT",
            "--expected-revision", "$GITHUB_SHA", "--toolchain-id", "$P06_CHECKED_TOOLCHAIN_ID",
            "--toolchain-cache-key", "$P06_CHECKED_TOOLCHAIN_CACHE", "--third-party-cache-key", "$P06_CHECKED_DEPENDENCY_CACHE",
            "--expected-third-party-key", "$P06_CHECKED_DEPENDENCY_KEY", "--backend", "simx", "--format", "both",
            "2>&1", "|", "tee", "$P06_CHECKED_ROOT/evidence/preparation.log",
        ])

    def test_native_command_passes_expected_revision_without_scope_or_budget_overrides(self):
        execute = self.one("name", EXECUTE)
        self.assertEqual(set(execute), {"name", "run"})
        command = one_command(execute, pipefail=True)
        self.assertEqual(command, [
            "python3", "ci/project/p06_checked_execute.py", "--source-dir", "$PWD",
            "--tools-dir", "$P06_CHECKED_ROOT/tools", "--expected-revision", "$GITHUB_SHA",
            "--work-dir", "$P06_CHECKED_ROOT/native-work", "--output", "$P06_CHECKED_ROOT/evidence/checked-counters",
            "2>&1", "|", "tee", "$P06_CHECKED_ROOT/evidence/execution.log",
        ])
        arguments = command[2:command.index("2>&1")]
        parser = runner.argument_parser()
        parsed = parser.parse_args(arguments)
        self.assertEqual(parsed.expected_revision, "$GITHUB_SHA")
        self.assertIsNone(parsed.osversion)
        for option in ("--development", "--case", "--jobs", "--threads", "--min-free-gib",
                       "--max-rss-bytes", "--run-timeout-seconds", "--skip-ordinary", "--qualified"):
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                parser.parse_args([*arguments, option, "1"])
            self.assertEqual(error.exception.code, 2)

    def test_resource_preflight_retains_identity_before_rejecting_insufficient_or_unknown_resources(self):
        body = python_body(self.one("name", IDENTITY), "python3 - <<'PY'")
        for disk, memory, blocked in ((15 * GIB, 4 * GIB, False), (15 * GIB - 1, 4 * GIB, True),
                                      (15 * GIB, 4 * GIB - 1, True), (15 * GIB, None, True)):
            with self.subTest(disk=disk, memory=memory), tempfile.TemporaryDirectory(prefix="checked-ci-budget-") as temporary:
                root = Path(temporary)
                env = {"RUNNER_TEMP": str(root), "GITHUB_ENV": str(root / "github-env"),
                       "GITHUB_SHA": "1" * 40, "GITHUB_EVENT_NAME": "pull_request", "GITHUB_RUN_ID": "123",
                       "GITHUB_RUN_ATTEMPT": "2", "GITHUB_JOB": "native-counters",
                       "GITHUB_REPOSITORY": "host-test/synthetic", "GITHUB_REF": "refs/pull/1/merge"}
                with contextlib.chdir(ROOT), mock.patch.dict(os.environ, env), \
                        mock.patch.object(sys, "path", list(sys.path)), \
                        mock.patch.object(shutil, "disk_usage", return_value=SimpleNamespace(free=disk)), \
                        mock.patch.object(preflight, "available_memory_bytes", return_value=memory):
                    if blocked:
                        with self.assertRaisesRegex(SystemExit, "15 GiB disk reserve"):
                            exec(compile(body, "<checked-workflow-resource-preflight>", "exec"), {})
                    else:
                        exec(compile(body, "<checked-workflow-resource-preflight>", "exec"), {})
                    evidence = root / "p06-checked-counters/evidence"
                    data = json.loads((evidence / "job.json").read_text())
                    self.assertEqual(data["free_disk_bytes_before_cache"], disk)
                    self.assertEqual(data["available_memory_bytes_before_cache"], memory)
                    for key in ("qualified", "ready_for_warm", "acceptance_claimed"):
                        self.assertIs(data[key], False)
                    self.assertEqual(data["native_execution"], "not_run")
                    self.assertEqual(data["requested_modes"], ["ordinary", "checked"])
                    for key, value in env.items():
                        if key.startswith("GITHUB_") and key != "GITHUB_ENV":
                            self.assertEqual(data[key], value)
                    self.assertEqual((evidence / "workflow.yml").read_bytes(), WORKFLOW.read_bytes())
                    self.assertEqual(data["workflow_sha256"], hashlib.sha256(WORKFLOW.read_bytes()).hexdigest())
                    self.assertEqual((root / "github-env").read_text(),
                                     "P06_CHECKED_ROOT=" + str(root / "p06-checked-counters") + "\n")
                    with self.assertRaises(FileExistsError):
                        exec(compile(body, "<checked-workflow-resource-preflight>", "exec"), {})
                    self.assertEqual(json.loads((evidence / "job.json").read_text()), data)

    def test_pinned_python_identity_retains_and_rejects_every_mismatch(self):
        self.assertEqual(scalars(children(self.one("uses", "actions/setup-python@v5"), "with", 10)), {
            "python-version": "'3.12.14'", "architecture": "x64", "check-latest": "false",
        })
        body = python_body(self.one("name", PYTHON_IDENTITY), "python3 -I - <<'PY'")
        cases = [("match", (3, 12, 14), "CPython", "linux", "same", False),
                 ("symlink", (3, 12, 14), "CPython", "linux", "alias", False),
                 ("version", (3, 12, 13), "CPython", "linux", "same", True),
                 ("implementation", (3, 12, 14), "PyPy", "linux", "same", True),
                 ("platform", (3, 12, 14), "CPython", "darwin", "same", True),
                 ("missing", (3, 12, 14), "CPython", "linux", "missing", True),
                 ("different", (3, 12, 14), "CPython", "linux", "different", True)]
        for name, version, implementation, system, path_kind, rejected in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory(prefix="checked-ci-python-") as temporary:
                root = Path(temporary)
                (root / "evidence").mkdir()
                alias = root / "python3"
                alias.symlink_to(Path(sys.executable).resolve())
                path = {"same": sys.executable, "alias": str(alias), "missing": None,
                        "different": str(root / "different-python")}[path_kind]
                with mock.patch.dict(os.environ, {"P06_CHECKED_ROOT": str(root)}), \
                        mock.patch.object(sys, "version_info", version), mock.patch.object(sys, "platform", system), \
                        mock.patch.object(platform, "python_implementation", return_value=implementation), \
                        mock.patch.object(shutil, "which", return_value=path):
                    if rejected:
                        with self.assertRaisesRegex(SystemExit, "Python interpreter identity differs"):
                            exec(compile(body, "<checked-workflow-python-identity>", "exec"), {})
                    else:
                        exec(compile(body, "<checked-workflow-python-identity>", "exec"), {})
                data = json.loads((root / "evidence/python-provision.json").read_text())
                self.assertEqual(data, {"python_version": list(version), "implementation": implementation,
                                       "platform": system, "executable": sys.executable, "python3_on_path": path})

    def test_failed_producers_retain_both_streams_and_fail_actual_shell_pipelines(self):
        for label, log_name, program, first_argument in (
                ("Install baseline host dependencies", "host-dependencies.log", "sudo", "bash"),
                (PREPARE, "preparation.log", "python3", "ci/project/p04_ci_prepare.py"),
                (EXECUTE, "execution.log", "python3", "ci/project/p06_checked_execute.py")):
            with self.subTest(step=label), tempfile.TemporaryDirectory(prefix="checked-ci-pipeline-") as temporary:
                root = Path(temporary)
                (root / "evidence").mkdir()
                stub = root / program
                stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CHECKED_CI_ARGUMENTS"\n'
                                'printf "producer failed\\n"\nprintf "producer stderr\\n" >&2\nexit 37\n')
                stub.chmod(0o700)
                env = {"PATH": str(root) + os.pathsep + os.defpath, "P06_CHECKED_ROOT": str(root),
                       "CHECKED_CI_ARGUMENTS": str(root / "arguments"), "GITHUB_SHA": "1" * 40,
                       **{name: "synthetic-unused" for name in ("P06_CHECKED_TOOLCHAIN_ID", "P06_CHECKED_TOOLCHAIN_CACHE",
                            "P06_CHECKED_DEPENDENCY_CACHE", "P06_CHECKED_DEPENDENCY_KEY")}}
                result = subprocess.run(["/bin/bash", "-c", script(self.one("name", label))],
                    cwd=ROOT, env=env, text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 37, result.stderr)
                self.assertEqual((root / "evidence" / log_name).read_text(), "producer failed\nproducer stderr\n")
                self.assertEqual((root / "arguments").read_text().splitlines()[0], first_argument)

    def test_always_upload_keeps_all_evidence_with_source_run_and_attempt_identity(self):
        upload = self.one("uses", "actions/upload-artifact@v4")
        self.assertEqual(upload["if"], ("always()", []))
        self.assertEqual(scalars(children(upload, "with", 10)), {
            "name": "p06-checked-counters-${{ github.sha }}-run${{ github.run_id }}-attempt${{ github.run_attempt }}",
            "path": "${{ runner.temp }}/p06-checked-counters/evidence", "if-no-files-found": "error",
            "retention-days": "30", "compression-level": "6", "include-hidden-files": "true",
        })
        self.assertEqual(self.steps[-1], upload)
        for name in (PREPARE, EXECUTE):
            self.assertIn("$P06_CHECKED_ROOT/evidence/", script(self.one("name", name)))

    def test_shell_and_embedded_python_blocks_have_valid_syntax(self):
        for step in self.steps:
            if "run" in step:
                with self.subTest(step=step.get("name", step.get("id"))):
                    result = subprocess.run(["bash", "-n"], input=script(step), text=True,
                                            capture_output=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
        for name, invocation in ((IDENTITY, "python3 - <<'PY'"), (PYTHON_IDENTITY, "python3 -I - <<'PY'")):
            compile(python_body(self.one("name", name), invocation), name, "exec")


if __name__ == "__main__":
    unittest.main()
