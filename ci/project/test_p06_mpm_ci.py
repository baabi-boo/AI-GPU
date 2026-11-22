# SPDX-License-Identifier: Apache-2.0
"""Host-only checks of MPM CI trust, native execution wiring and failure retention."""

import ast
import contextlib
import io
import json
import os
import platform
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import baseline_process
import preflight
import p04_ci_prepare
import p06_mpm_synthesis as synthesis
import p06_mpm_execute as runner
from test_p05_ci_workflow import children, fields, steps, workflow


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/p06-mpm-transport.yml"
CATALOG = ROOT / "ci/testcases/unittest.yaml"
NEW_CASE = "hw-mpm-transport"


def scalar(value):
    if value.startswith(("'", '"')):
        return ast.literal_eval(value)
    if value in ("true", "false"):
        return value == "true"
    if value.isdecimal():
        return int(value)
    return value


def scalar_fields(mapping):
    if any(lines for _, lines in mapping.values()):
        raise AssertionError("expected scalar mapping fields")
    return {key: scalar(value) for key, (value, _) in mapping.items()}


def sequence(field):
    value, lines = field
    if value.startswith("[") and value.endswith("]") and not lines:
        return [scalar(item.strip()) for item in value[1:-1].split(",") if item.strip()]
    if value:
        raise AssertionError("expected a plain YAML sequence")
    result = []
    for line in lines:
        match = re.fullmatch(r"\s+- (.+)", line)
        if not match:
            raise AssertionError("invalid YAML sequence member: " + line)
        result.append(scalar(match[1]))
    return result


def script(mapping, indent=10):
    value, lines = mapping["run"]
    if value == "|":
        return "\n".join(line[indent:] for line in lines) + "\n"
    if lines:
        raise AssertionError("unsupported shell scalar")
    return scalar(value)


def catalog_cases():
    document = workflow(CATALOG)
    blocks = []
    for line in document["tests"][1]:
        if line.startswith("  - "):
            blocks.append(["    " + line[4:]])
        elif blocks:
            blocks[-1].append(line)
        else:
            raise AssertionError("expected a catalog case")
    return [fields(block, 4) for block in blocks]


def command(step):
    lines = script(step).replace("\\\n", " ").splitlines()
    if not lines or shlex.split(lines.pop(0)) != ["set", "-euo", "pipefail"]:
        raise AssertionError("retained command must fail on pipeline errors")
    if len(lines) != 1:
        raise AssertionError("expected one retained command")
    words = shlex.split(lines[0])
    return words[:words.index("2>&1")] if "2>&1" in words else words


def python_blocks(text):
    lines = iter(text.splitlines())
    for line in lines:
        match = re.search(r"\bpython3?\b[^\n]*<<\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\s*$", line)
        if match:
            body = []
            for line in lines:
                if line == match[1]:
                    break
                body.append(line)
            else:
                raise AssertionError("unterminated Python heredoc")
            yield "\n".join(body) + "\n"


def covers(patterns, name):
    return any(re.fullmatch(re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", "[^/]*"), name)
               for pattern in patterns)


class MpmTransportCiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = workflow(WORKFLOW)
        cls.events = children(cls.document, "on", 2)
        cls.jobs = children(cls.document, "jobs", 2)
        cls.job = children(cls.jobs, "native-transport", 4)
        cls.steps = steps(cls.job)
        cls.circuit_job = children(cls.jobs, "paired-synthesis", 4)
        cls.circuit_steps = steps(cls.circuit_job)
        cls.cases = catalog_cases()
        cls.case = next(case for case in cls.cases if scalar(case["id"][0]) == NEW_CASE)

    def one(self, field, value, sequence=None):
        sequence = self.steps if sequence is None else sequence
        found = [step for step in sequence if scalar(step.get(field, ("", []))[0]) == value]
        self.assertEqual(len(found), 1, (field, value))
        return found[0]

    def using(self, action, sequence=None):
        sequence = self.steps if sequence is None else sequence
        found = [step for step in sequence if step.get("uses", ("", []))[0].split("@")[0] == action]
        self.assertEqual(len(found), 1, action)
        return found[0]

    def invokes(self, filename, sequence=None):
        sequence = self.steps if sequence is None else sequence
        found = [step for step in sequence if "run" in step and filename in script(step)]
        self.assertEqual(len(found), 1, filename)
        return found[0]

    def test_triggers_and_hosted_read_only_trust_boundary(self):
        self.assertEqual(set(self.events), {"push", "pull_request", "workflow_dispatch"})
        push = children(self.events, "push", 4)
        self.assertEqual(sequence(push["branches"]), ["master"])
        self.assertEqual(set(self.jobs), {"native-transport", "paired-synthesis"})
        self.assertRegex(scalar(self.job["runs-on"][0]), r"^ubuntu-\d{2}\.\d{2}$")
        self.assertEqual(scalar_fields(children(self.document, "permissions", 2)), {"contents": "read"})
        self.assertNotIn("permissions", self.job)
        self.assertNotIn("secrets", self.job)
        self.assertNotIn("environment", self.job)
        self.assertNotIn("uses", self.job)
        self.assertNotIn("continue-on-error", self.job)
        checkout = scalar_fields(children(self.using("actions/checkout"), "with", 10))
        self.assertIs(checkout["persist-credentials"], False)
        self.assertEqual(checkout["submodules"], "recursive")
        self.assertNotRegex(WORKFLOW.read_text(), r"secrets\s*(?:\.|\[)|self-hosted|write-all")
        python_setup = scalar_fields(children(self.using("actions/setup-python"), "with", 10))
        self.assertNotIn("cache", python_setup)
        self.assertNotIn("cache-dependency-path", python_setup)
        allowed = {"actions/checkout", "actions/setup-python", "actions/cache/restore", "actions/upload-artifact"}
        for step in self.steps + self.circuit_steps:
            with self.subTest(step=step.get("name", step.get("uses"))):
                self.assertNotIn("continue-on-error", step)
                if "uses" in step:
                    self.assertIn(step["uses"][0].split("@")[0], allowed)
                if "run" in step:
                    self.assertEqual(shlex.split(script(step).splitlines()[0]), ["set", "-euo", "pipefail"])
                    self.assertNotRegex(script(step), r"\|\|\s*(?:true|:)|set\s+\+|(?:^|\s)exit\s+0\b")
                    self.assertNotRegex(script(step), r"git\s+push|gh\s+(?:api|cache)\b")

    def test_native_execution_and_failed_preparation_are_not_conditionally_skipped(self):
        prepare = self.invokes("ci/project/p04_ci_prepare.py")
        execute = self.invokes("ci/project/p06_mpm_execute.py")
        for step in (prepare, execute):
            self.assertNotIn("if", step)
            self.assertNotIn("continue-on-error", step)
        self.assertNotIn("if", self.job)
        self.assertLess(self.steps.index(prepare), self.steps.index(execute))
        argv = command(execute)
        self.assertEqual(argv[:2], ["python3", "ci/project/p06_mpm_execute.py"])
        options = runner.argument_parser().parse_args(argv[2:])
        self.assertEqual((options.xlen, options.engines), ("both", "both"))
        self.assertFalse(options.development)
        self.assertEqual(str(options.source_dir), "$PWD")
        self.assertEqual(str(options.tools_dir), "$P06_MPM_ROOT/tools")
        self.assertEqual(str(options.work_dir), "$P06_MPM_ROOT/work")
        self.assertEqual(str(options.output), "$P06_MPM_ROOT/evidence/transport")
        self.assertNotIn("--development", WORKFLOW.read_text())

    def test_parent_sensitivity_uses_pinned_source_and_separate_execution_roots(self):
        parent = self.invokes("ci/project/p06_mpm_parent.py")
        native = self.invokes("ci/project/p06_mpm_execute.py")
        reference = self.one("id", "reference")
        self.assertEqual(parent["if"][0],
            "${{ !cancelled() && steps.preparation.outcome == 'success' && steps.reference.outcome == 'success' }}")
        self.assertLess(self.steps.index(reference), self.steps.index(native))
        self.assertLess(self.steps.index(native), self.steps.index(parent))
        argv = command(parent)
        self.assertEqual(argv[:2], ["python3", "ci/project/p06_mpm_parent.py"])
        options = dict(zip(argv[2::2], argv[3::2]))
        self.assertEqual(options, {"--source-dir": "$PWD", "--tools-dir": "$P06_MPM_ROOT/tools",
            "--work-dir": "$P06_MPM_ROOT/parent-work", "--output": "$P06_MPM_ROOT/evidence/parent"})
        self.assertNotIn("continue-on-error", parent)
        pin = "4df7186edbca82b21b2b8cba9b3b192248b99209"
        lines = script(reference).replace("\\\n", " ").splitlines()[1:]
        fetch = shlex.split(lines[0])
        self.assertEqual(fetch[:9], ["git", "-c", "protocol.version=2", "fetch", "--no-tags",
                                    "--depth=1", "origin", pin, "2>&1"])
        self.assertEqual(shlex.split(lines[1]), ["git", "cat-file", "-e", pin + "^{commit}"])

    def test_circuit_job_inherits_read_only_trust_and_retains_failures(self):
        job, job_steps = self.circuit_job, self.circuit_steps
        self.assertRegex(scalar(job["runs-on"][0]), r"^ubuntu-\d{2}\.\d{2}$")
        self.assertTrue(0 < scalar(job["timeout-minutes"][0]) <= 90)
        for field in ("if", "permissions", "secrets", "environment", "uses", "continue-on-error"):
            self.assertNotIn(field, job)
        checkout = scalar_fields(children(self.using("actions/checkout", job_steps), "with", 10))
        self.assertIs(checkout["persist-credentials"], False)
        self.assertEqual(checkout["submodules"], "recursive")
        python = scalar_fields(children(self.using("actions/setup-python", job_steps), "with", 10))
        self.assertEqual(python["python-version"], "3.12.14")
        self.assertIs(python["check-latest"], False)
        self.assertNotIn("cache", python)
        self.assertNotIn("cache-dependency-path", python)
        self.assertEqual(scalar_fields(children(job, "env", 6)), scalar_fields(children(self.job, "env", 6)))
        self.assertEqual(scalar_fields(children(children(job, "defaults", 6), "run", 8))["shell"], "bash")
        cache = self.using("actions/cache/restore", job_steps)
        values = scalar_fields(children(cache, "with", 10))
        self.assertEqual(values["path"], "tools")
        for field in ("key", "restore-keys"):
            self.assertIn("steps.pins.outputs.toolchain", values[field])
        execute = self.invokes("ci/project/p06_mpm_synthesis.py", job_steps)
        self.assertNotIn("if", execute)
        argv = command(execute)
        self.assertEqual(argv[:2], ["python3", "ci/project/p06_mpm_synthesis.py"])
        self.assertEqual(dict(zip(argv[2::2], argv[3::2])), {
            "--source-dir": "$PWD", "--tools-dir": "$P06_MPM_CIRCUITS/tools",
            "--work-dir": "$P06_MPM_CIRCUITS/work", "--output": "$P06_MPM_CIRCUITS/evidence/synthesis"})
        self.assertNotIn("--update-baseline", WORKFLOW.read_text())
        upload = self.using("actions/upload-artifact", job_steps)
        self.assertEqual(upload["if"][0], "always()")
        artifact = scalar_fields(children(upload, "with", 10))
        self.assertEqual(artifact["path"], "${{ runner.temp }}/p06-mpm-circuits/evidence")
        self.assertEqual(artifact["if-no-files-found"], "error")
        self.assertTrue(artifact["include-hidden-files"])
        self.assertTrue(1 <= artifact["retention-days"] <= 90)
        self.assertTrue(all(name in artifact["name"] for name in ("github.sha", "github.run_id", "github.run_attempt")))
        self.assertEqual(job_steps[-1], upload)

    def test_both_jobs_enforce_resource_preflight_before_any_cache_restore(self):
        for job_steps, directory in ((self.steps, "p06-mpm-transport"),
                                     (self.circuit_steps, "p06-mpm-circuits")):
            initializer = next(step for step in job_steps if "run" in step and "job.json" in script(step))
            cache_positions = [i for i, step in enumerate(job_steps)
                               if "cache" in step.get("uses", ("", []))[0]]
            self.assertLess(job_steps.index(initializer), min(cache_positions))
            body, = python_blocks(script(initializer))
            for disk, memory, blocked in ((30 * 1024**3, 8 * 1024**3, False),
                                           (15 * 1024**3 - 1, 8 * 1024**3, True),
                                           (30 * 1024**3, 4 * 1024**3 - 1, True)):
                with self.subTest(job=directory, disk=disk, memory=memory):
                    with tempfile.TemporaryDirectory(prefix="mpm-ci-preflight-") as temporary:
                        root = Path(temporary).resolve()
                        environment = {key: "synthetic" for key in ("GITHUB_SHA", "GITHUB_EVENT_NAME", "GITHUB_RUN_ID",
                            "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "GITHUB_REPOSITORY", "GITHUB_REF")}
                        environment.update(RUNNER_TEMP=str(root), GITHUB_ENV=str(root / "environment"))
                        with mock.patch.dict(os.environ, environment), mock.patch.object(sys, "path", list(sys.path)), \
                                mock.patch.object(preflight, "available_memory_bytes", return_value=memory), \
                                mock.patch("shutil.disk_usage", return_value=SimpleNamespace(free=disk)):
                            if blocked:
                                with self.assertRaisesRegex(SystemExit, "15 GiB disk reserve and 4 GiB"):
                                    exec(compile(body, "<workflow-preflight>", "exec"), {})
                            else:
                                exec(compile(body, "<workflow-preflight>", "exec"), {})
                        report = json.loads((root / directory / "evidence/job.json").read_text())
                        self.assertEqual(report["free_disk_bytes_before_cache"], disk)
                        self.assertEqual(report["available_memory_bytes_before_cache"], memory)
                        self.assertFalse(report["acceptance_claimed"])
                        if directory == "p06-mpm-circuits":
                            self.assertFalse(report["physical_timing_claimed"])
                            self.assertFalse(report["baseline_gate_pass_claimed"])
                            self.assertEqual(report["initial_measurements"], "not_run")

    def circuit_preparation(self, cache=None, fail_command=None):
        preparation = self.invokes("from baseline_process import GIB, MIB, run_bounded", self.circuit_steps)
        self.assertNotIn("if", preparation)
        body, = python_blocks(script(preparation))
        identity = "v3.0.2-" + "a" * 40
        with tempfile.TemporaryDirectory(prefix="mpm-ci-provision-") as temporary:
            base = Path(temporary).resolve()
            source, workspace = base / "source", base / "workspace"
            (source / "tools").mkdir(parents=True)
            (workspace / "evidence").mkdir(parents=True)
            calls = []
            def bounded(argv, cwd, environment, log, **limits):
                calls.append({"id": log.stem, "argv": argv, "environment": environment, "limits": limits})
                if log.stem == "configure-tools":
                    (cwd / "ci").mkdir()
                    (cwd / "ci/toolchain_install.sh").write_text("# synthetic installer; never executed\n")
                failed = log.stem == fail_command
                log.write_text("synthetic provisioning process; no downloads or native builds\n")
                return {"outcome": "fail" if failed else "pass", "cleanup_complete": True,
                        "reason": "nonzero_exit" if failed else None, "exit_code": 1 if failed else 0,
                        "process_started": True}
            environment = {"P06_MPM_CIRCUITS": str(workspace), "P06_MPM_TOOLCHAIN_ID": identity,
                           "P06_MPM_TOOLCHAIN_CACHE": "Linux-toolchain-" + identity + "-lite" if cache is None else cache}
            with mock.patch.dict(os.environ, environment), mock.patch.object(sys, "path", list(sys.path)), \
                    mock.patch.object(sys, "version_info", (3, 12, 14)), \
                    mock.patch.object(platform, "python_implementation", return_value="CPython"), \
                    mock.patch.object(Path, "cwd", return_value=source), \
                    mock.patch.object(preflight, "available_memory_bytes", return_value=8 * 1024**3), \
                    mock.patch("shutil.disk_usage", return_value=SimpleNamespace(free=30 * 1024**3)), \
                    mock.patch.object(baseline_process, "run_bounded", side_effect=bounded):
                if cache is not None or fail_command:
                    with self.assertRaises(SystemExit):
                        exec(compile(body, "<workflow-provisioning>", "exec"), {})
                else:
                    exec(compile(body, "<workflow-provisioning>", "exec"), {})
            report = json.loads((workspace / "evidence/preparation.json").read_text())
            self.assertFalse(report["acceptance_claimed"])
            for call in calls:
                self.assertEqual(call["limits"]["max_rss_bytes"], 4 * 1024**3)
                self.assertEqual(call["limits"]["min_free_bytes"], 15 * 1024**3)
                self.assertEqual(call["limits"]["max_log_bytes"], 16 * 1024**2)
                self.assertTrue(0 < call["limits"]["timeout_seconds"] <= 300)
                self.assertEqual(call["environment"]["TOOLCHAIN_REV"], "a" * 40)
                self.assertEqual(call["environment"]["MAKEFLAGS"], "-j2")
                self.assertEqual(call["environment"]["THREADS"], "1")
            return report, calls

    def test_circuit_provisioning_uses_only_pinned_bounded_prerequisites(self):
        report, calls = self.circuit_preparation()
        self.assertEqual(report["outcome"], "pass")
        commands = {call["id"]: call["argv"] for call in calls}
        self.assertEqual(set(commands), {"python-packages", "configure-tools", "install-foldsim",
                                        "fetch-reference", "verify-reference"})
        packages = commands["python-packages"]
        for argument in ("-I", "--isolated", "--no-cache-dir", "--only-binary=:all:", "--no-deps"):
            self.assertIn(argument, packages)
        self.assertEqual(packages[-2:], ["PyYAML==6.0.2", "pyslang==12.2.0"])
        self.assertEqual(commands["install-foldsim"][0], "bash")
        self.assertEqual(commands["install-foldsim"][2:], ["--foldsim"])
        pin = "4df7186edbca82b21b2b8cba9b3b192248b99209"
        self.assertEqual(commands["fetch-reference"],
                         ["git", "-c", "protocol.version=2", "fetch", "--no-tags", "--depth=1", "origin", pin])
        self.assertEqual(commands["verify-reference"], ["git", "cat-file", "-e", pin + "^{commit}"])

    def test_circuit_cache_misses_and_provisioning_failures_remain_retained_failures(self):
        for key in ("", "Linux-toolchain-v3.0.2-" + "b" * 40 + "-lite"):
            with self.subTest(cache=key):
                report, calls = self.circuit_preparation(cache=key)
                self.assertEqual(report["outcome"], "blocked")
                self.assertIn("matching pinned toolchain cache is unavailable", report["reason"])
                self.assertEqual(calls, [])
        report, calls = self.circuit_preparation(fail_command="install-foldsim")
        self.assertEqual(report["outcome"], "blocked")
        self.assertEqual(calls[-1]["id"], "install-foldsim")
        self.assertEqual(report["commands"][-1]["outcome"], "fail")
        self.assertIn("install-foldsim failed: nonzero_exit", report["reason"])

    def test_cache_restoration_is_pinned_read_only_and_checked_before_execution(self):
        caches = [step for step in self.steps if "cache" in step.get("uses", ("", []))[0]]
        self.assertEqual(len(caches), 2)
        for step in caches:
            self.assertEqual(step["uses"][0].split("@")[0], "actions/cache/restore")
            self.assertNotIn("if", step)
        tools = scalar_fields(children(self.one("id", "toolchain"), "with", 10))
        dependencies = scalar_fields(children(self.one("id", "dependencies"), "with", 10))
        self.assertEqual(tools["path"], "tools")
        self.assertIn("steps.pins.outputs.toolchain", tools["key"])
        self.assertIn("steps.pins.outputs.toolchain", tools["restore-keys"])
        self.assertEqual(dependencies["path"], "third_party")
        self.assertIn("hashFiles('third_party/Makefile', '.gitmodules')", dependencies["key"])
        self.assertNotIn("restore-keys", dependencies)
        prepare = self.invokes("ci/project/p04_ci_prepare.py")
        values = scalar_fields(children(prepare, "env", 10))
        self.assertEqual(values["P06_MPM_TOOLCHAIN_CACHE"], "${{ steps.toolchain.outputs.cache-matched-key }}")
        self.assertEqual(values["P06_MPM_DEPENDENCY_CACHE"], "${{ steps.dependencies.outputs.cache-matched-key }}")
        self.assertEqual(values["P06_MPM_DEPENDENCY_KEY"], dependencies["key"])
        argv = command(prepare)
        for option, expected in (("--toolchain-cache-key", "$P06_MPM_TOOLCHAIN_CACHE"),
                                 ("--third-party-cache-key", "$P06_MPM_DEPENDENCY_CACHE"),
                                 ("--expected-third-party-key", "$P06_MPM_DEPENDENCY_KEY"),
                                 ("--expected-revision", "$GITHUB_SHA")):
            self.assertEqual(argv[argv.index(option) + 1], expected)
        self.assertTrue(all(self.steps.index(step) < self.steps.index(prepare) for step in caches))
        for step in self.steps:
            if "run" in step:
                self.assertNotRegex(script(step), r"toolchain_install|(?:curl|wget)\s|make\s.*third_party|git\s+clone")

    def test_missing_or_mismatched_cache_fails_with_a_retained_blocked_receipt(self):
        pins, errors = p04_ci_prepare.read_pins(ROOT)
        self.assertEqual(errors, [])
        identity = pins["TOOLCHAIN_REV"] + "-" + "a" * 40
        tool_key = "Linux-toolchain-" + identity + "-lite"
        dependency_key = "Linux-thirdparty-" + "b" * 64
        for tools, dependencies in (("", dependency_key), (tool_key, ""),
                                    (tool_key, "Linux-thirdparty-" + "c" * 64)):
            with self.subTest(tools=bool(tools), dependencies=dependencies):
                with tempfile.TemporaryDirectory(prefix="mpm-ci-cache-") as temporary:
                    workspace = Path(temporary).resolve()
                    with contextlib.redirect_stdout(io.StringIO()):
                        result = p04_ci_prepare.main([
                            "--source-dir", str(ROOT), "--workspace-dir", str(workspace),
                            "--expected-revision", "a" * 40, "--toolchain-id", identity,
                            "--toolchain-cache-key", tools, "--third-party-cache-key", dependencies,
                            "--expected-third-party-key", dependency_key, "--backend", "rtlsim", "--format", "both"])
                    self.assertNotEqual(result, 0)
                    report = json.loads((workspace / "evidence/preparation.json").read_text())
                    self.assertEqual(report["outcome"], "blocked")
                    self.assertEqual(report["native_execution"], "not_run")
                    self.assertFalse(report["tools_relocated"])
                    self.assertFalse(report["acceptance_claimed"])
                    self.assertIn("cache is unavailable", report["reason"])

    def test_resource_budgets_and_failure_artifact_retention(self):
        self.assertTrue(0 < scalar(self.job["timeout-minutes"][0]) <= 90)
        self.assertEqual(scalar_fields(children(children(self.job, "defaults", 6), "run", 8))["shell"], "bash")
        for environment in (scalar_fields(children(self.job, "env", 6)),
                            scalar_fields(children(self.case, "env", 6))):
            self.assertEqual(environment["THREADS"], "1")
            self.assertEqual(environment["MAKEFLAGS"], "-j2")
            self.assertEqual(environment["CMAKE_BUILD_PARALLEL_LEVEL"], "2")
            self.assertEqual(environment["CCACHE_DISABLE"], "1")
            self.assertEqual(environment["OBJCACHE"], "")
            self.assertEqual(environment["PROFILE"], "")
        self.assertGreaterEqual(runner.BUDGET["min_free_bytes"], 15 * 1024**3)
        self.assertLessEqual(runner.BUDGET["max_rss_bytes"], 4 * 1024**3)
        self.assertLessEqual(runner.BUDGET["max_log_bytes"], 16 * 1024**2)
        for name, maximum in (("configure", 120), ("build", 1800), ("run", 180)):
            self.assertTrue(0 < runner.TIMEOUTS[name] <= maximum)
        upload = self.using("actions/upload-artifact")
        self.assertEqual(scalar(upload["if"][0]), "always()")
        values = scalar_fields(children(upload, "with", 10))
        self.assertEqual(values["if-no-files-found"], "error")
        self.assertTrue(values["include-hidden-files"])
        self.assertTrue(1 <= values["retention-days"] <= 90)
        self.assertEqual(values["path"], "${{ runner.temp }}/p06-mpm-transport/evidence")
        self.assertTrue(all(name in values["name"] for name in ("github.sha", "github.run_id", "github.run_attempt")))
        self.assertEqual(self.steps[-1], upload)

    def test_workflow_triggers_cover_actual_source_and_generated_template_inputs(self):
        required = set(runner.CRITICAL) | set(synthesis.INPUTS) | {
            WORKFLOW.relative_to(ROOT).as_posix(), CATALOG.relative_to(ROOT).as_posix(),
            "Makefile.in", "ci/toolchain_rev.sh", "ci/install_dependencies.sh",
            "ci/project/p06_mpm_parent.py", "ci/toolchain_install.sh.in",
            "hw/unittest/Makefile", "hw/unittest/common/vl_simulator.h", "third_party/Makefile",
        }
        self.assertTrue((ROOT / "hw/unittest/verilator.vlt.in").is_file())
        self.assertIn("hw/unittest/verilator.vlt.in", required)
        for event in ("push", "pull_request"):
            with self.subTest(event=event):
                patterns = sequence(children(self.events, event, 4)["paths"])
                self.assertTrue(patterns)
                self.assertFalse(any(pattern.startswith("!") for pattern in patterns))
                self.assertEqual(sorted(name for name in required if not covers(patterns, name)), [])

    def test_catalog_touches_cover_native_critical_inputs_using_prefix_semantics(self):
        prefixes = sequence(self.case["touches"])
        self.assertEqual(sorted(name for name in runner.CRITICAL
                                if not any(name.startswith(prefix) for prefix in prefixes)), [])

    def test_catalog_development_is_explicit_and_scoped_to_the_new_case(self):
        names = [scalar(case["id"][0]) for case in self.cases]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual([scalar(case["id"][0]) for case in self.cases
                          if "--development" in script(case, 6)], [NEW_CASE])
        self.assertEqual(scalar(self.case["via"][0]), "script")
        self.assertEqual(sequence(self.case["xlen"]), [32, 64])
        self.assertNotIn("driver", self.case)
        self.assertNotIn("drivers", self.case)
        inherited = {scalar(case["id"][0]): case for case in self.cases}
        for name, expected in (("sw", "make -C tests/unittest run"),
                               ("hw", "make -C hw/unittest"),
                               ("hw-fpu", "make -C hw/unittest run-fpu")):
            self.assertEqual(shlex.split(script(inherited[name], 6)), shlex.split(expected))

    def catalog_probe(self, xlen, configuration):
        with tempfile.TemporaryDirectory(prefix="mpm-ci-catalog-") as temporary:
            root = Path(temporary).resolve()
            source, tools, build = (root / name for name in ("source", "tools", "build"))
            for directory in (source / "ci/project", tools, build):
                directory.mkdir(parents=True)
            (source / "ci/project/p06_mpm_execute.py").write_text("# intercepted before execution\n")
            text = configuration.replace("@SOURCE@", str(source)).replace("@TOOLS@", str(tools))
            (build / "config.mk").write_text(text)
            body, = python_blocks(script(self.case, 6).replace("{xlen}", str(xlen)))
            bootstrap = ("import json, os\n"
                         "def capture(executable, argv):\n"
                         "    print('CAPTURE=' + json.dumps(argv))\n"
                         "    raise SystemExit(0)\n"
                         "os.execv = capture\n"
                         "exec(compile(" + repr(body) + ", '<catalog>', 'exec'))\n")
            result = subprocess.run([sys.executable, "-I", "-"], input=bootstrap, cwd=build,
                                    capture_output=True, text=True, timeout=10)
            captured = [line.removeprefix("CAPTURE=") for line in result.stdout.splitlines()
                        if line.startswith("CAPTURE=")]
            if captured:
                argv = json.loads(captured[0])
                self.assertEqual(Path(argv[1]), source / "ci/project/p06_mpm_execute.py")
                args = runner.argument_parser().parse_args(argv[2:])
                self.assertEqual(args.source_dir, source)
                self.assertEqual(args.tools_dir, tools)
                self.assertEqual((args.xlen, args.engines, args.development), (str(xlen), "both", True))
                self.assertEqual(args.work_dir.parent, args.output.parent)
                self.assertEqual(args.work_dir.parent.parent, root)
                self.assertFalse(args.work_dir.exists())
                self.assertFalse(args.output.exists())
            return result, captured

    def test_catalog_executes_the_actual_runner_in_fresh_selected_width_workspaces(self):
        for xlen in (32, 64):
            with self.subTest(xlen=xlen):
                result, captured = self.catalog_probe(xlen,
                    f"VORTEX_HOME ?= @SOURCE@\nTOOLDIR ?= @TOOLS@\nXLEN ?= {xlen}\n")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(captured), 1)

    def test_catalog_rejects_width_mismatch_duplicate_or_evaluated_configuration(self):
        good = "VORTEX_HOME ?= @SOURCE@\nTOOLDIR ?= @TOOLS@\nXLEN ?= 64\n"
        for configuration in (good.replace("XLEN ?= 64", "XLEN ?= 32"),
                              good + "XLEN ?= 64\n", good.replace("?= @TOOLS@", ":= @TOOLS@"),
                              good.replace("@TOOLS@", "$(shell false)")):
            with self.subTest(configuration=configuration):
                result, captured = self.catalog_probe(64, configuration)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(captured, [])

    def test_shell_blocks_and_embedded_python_parse_without_native_execution(self):
        snippets = [script(step) for step in self.steps + self.circuit_steps if "run" in step]
        snippets.append(script(self.case, 6).replace("{xlen}", "64"))
        python_count = 0
        for index, snippet in enumerate(snippets):
            with self.subTest(snippet=index):
                result = subprocess.run(["bash", "-n"], input=snippet, text=True,
                                        capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                for body in python_blocks(snippet):
                    ast.parse(body)
                    python_count += 1
        self.assertGreaterEqual(python_count, 5)
        ast.parse((ROOT / "ci/project/p06_mpm_execute.py").read_text())


class MpmNativeExecutionWiringTests(unittest.TestCase):
    def exercise(self, failed_cell=None):
        with tempfile.TemporaryDirectory(prefix="mpm-ci-wiring-") as temporary:
            base = Path(temporary).resolve()
            tools = base / "tools"
            tools.mkdir()
            paths = {"source": ROOT, "tools": tools, "work": base / "work", "output": base / "evidence"}
            args = runner.argument_parser().parse_args([
                "--tools-dir", str(tools), "--work-dir", str(paths["work"]),
                "--output", str(paths["output"]), "--xlen", "both", "--engines", "both"])
            def bounded(argv, cwd, environment, log, **limits):
                outcome = "pass"
                text = "synthetic process seam; no native execution\n"
                if "--version" in argv:
                    pass
                elif argv[0] == str(ROOT / "configure"):
                    for directory in runner.UNITS.values():
                        (cwd / directory).mkdir(parents=True)
                    for name in runner.GENERATED:
                        path = cwd / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text("synthetic generated input\n")
                    for name in runner.COPIED:
                        path = cwd / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes((ROOT / name).read_bytes())
                    width = next(word.split("=", 1)[1] for word in argv if word.startswith("--xlen="))
                    (cwd / "config.mk").write_text(
                        f"XLEN ?= {width}\nPROFILE ?=\nVORTEX_HOME ?= {ROOT}\nTOOLDIR ?= {tools}\n")
                elif Path(argv[0]).name == "make":
                    engine = "simx" if cwd.name == "simx" else "rtl"
                    binary = cwd / runner.BINARIES[engine]
                    binary.write_text("synthetic binary identity\n")
                    binary.chmod(0o700)
                    if engine == "simx":
                        (cwd / "simx_config.stamp").write_text("synthetic compiler identity\n")
                elif Path(argv[0]).name in runner.BINARIES.values():
                    engine = "simx" if cwd.name == "simx" else "rtl"
                    variant = cwd.parents[1 if engine == "simx" else 2].name
                    xlen, _, perf = variant.removeprefix("rv").split("-")
                    cell = variant + "-" + engine
                    outcome = "fail" if cell == failed_cell else "pass"
                    text = (f"MPM transport: XLEN={xlen} PERF={perf}\nPASSED: 9 MPM transport checks\n"
                            if engine == "simx" else
                            f"PASSED mpm_transport RV{xlen} PERF={int(perf == 'on')} TCU=0 "
                            "read_count=9 assertion_count=9 ignored=1 response_edges=2 counter_bits=44\n")
                log.write_text(text)
                return {"outcome": outcome, "reason": "exit_zero" if outcome == "pass" else "nonzero_exit",
                        "process_started": True, "cleanup_complete": True, "exit_code": 0 if outcome == "pass" else 1}

            tool_snapshot = {"tools": {name: {"path": "/synthetic/" + name}
                                       for name in ("make", "g++", "python3", "verilator")},
                             "dependencies": {}, "missing": []}
            with mock.patch.object(runner, "source_snapshot", return_value={"synthetic": True}), \
                    mock.patch.object(runner, "check_source"), \
                    mock.patch.object(runner, "tools_snapshot", return_value=tool_snapshot), \
                    mock.patch.object(runner, "available_memory_bytes", return_value=8 * 1024**3), \
                    mock.patch.object(runner.shutil, "disk_usage", return_value=SimpleNamespace(free=30 * 1024**3)), \
                    mock.patch.object(runner, "run_bounded", side_effect=bounded):
                report = runner.execute(args, paths)
            self.assertEqual(json.loads((paths["output"] / "report.json").read_text()), report)
            expected = {f"rv{xlen}-perf-{perf}-{engine}"
                        for xlen in (32, 64) for perf in ("off", "on") for engine in ("rtl", "simx")}
            self.assertEqual({cell["id"] for cell in report["cells"]}, expected)
            self.assertEqual(len(report["variants"]), 4)
            commands = {item["id"]: item for item in report["commands"]}
            for cell in report["cells"]:
                with self.subTest(cell=cell["id"]):
                    self.assertTrue(cell["selected"])
                    self.assertTrue(cell["run_process_started"])
                    build = commands[cell["build_command"]]
                    run = commands[cell["run_command"]]
                    self.assertLess(report["commands"].index(build), report["commands"].index(run))
                    if cell["engine"] == "simx":
                        self.assertEqual(build["argv"][-3:], ["-f", "mpm_transport.mk", cell["binary_path"]])
                    else:
                        self.assertEqual(build["argv"][-1], "all")
                    self.assertEqual(run["argv"], [cell["binary_path"]])
                    self.assertEqual(Path(run["argv"][0]).name, runner.BINARIES[cell["engine"]])
                    self.assertTrue(Path(run["argv"][0]).is_relative_to(paths["work"]))
                    self.assertEqual(run["environment"]["THREADS"], "1")
                    if cell["perf"] == "off":
                        self.assertNotIn("PERF", run["environment"])
                        self.assertIn("PERF=", build["argv"])
                    else:
                        self.assertEqual(run["environment"]["PERF"], "1")
                        self.assertIn("PERF=1", build["argv"])
                    self.assertEqual(run["timeout_seconds"], runner.TIMEOUTS["run"])
            self.assertTrue(report["full_matrix_completed"])
            self.assertFalse(report["acceptance_claimed"])
            self.assertFalse(report["qualified"])
            self.assertEqual(report["absolute_no_wrap_bound"], "not_established")
            return report

    def test_all_eight_cells_request_distinct_build_and_native_binary_execution(self):
        report = self.exercise()
        self.assertEqual(report["outcome"], "pass")
        self.assertTrue(report["selected_matrix_complete"])

    def test_one_native_process_failure_prevents_full_matrix_success(self):
        report = self.exercise("rv64-perf-on-simx")
        self.assertEqual(report["outcome"], "fail")
        self.assertFalse(report["selected_matrix_complete"])
        self.assertFalse(report["formal_qualification_eligible"])
        self.assertEqual(report["full_matrix_outcome"], "fail")


if __name__ == "__main__":
    unittest.main()
