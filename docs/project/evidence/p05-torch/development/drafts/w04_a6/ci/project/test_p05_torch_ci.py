# SPDX-License-Identifier: Apache-2.0
"""Hosted framework workflow contracts; no accelerator qualification runs here."""

from pathlib import Path
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import tomllib
import unittest

from test_p05_ci_workflow import children, command, path_filters, scalars, script, steps, workflow


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/p05-torch.yml"
PYTHON_WORKFLOW = ROOT / ".github/workflows/p05-python.yml"
GOVERNANCE = ROOT / ".github/workflows/project-governance.yml"
CONTRACT = ROOT / "ci/project/p05_torch_contract.json"
LOCK = ROOT / "ci/project/p05_torch_requirements.lock"


def named(sequence, name):
    matches = [step for step in sequence if step.get("name", (None,))[0] == name]
    if len(matches) != 1:
        raise AssertionError("expected one workflow step: " + name)
    return matches[0]


def flattened(step):
    return shlex.split(script(step).replace("\\\n", " "))


class InstalledTorchWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = workflow(WORKFLOW)
        cls.python = workflow(PYTHON_WORKFLOW)
        cls.jobs = children(cls.workflow, "jobs", 2)
        cls.job = children(cls.jobs, "qualification", 4)
        cls.steps = steps(cls.job)
        cls.python_steps = steps(children(children(cls.python, "jobs", 2), "qualification", 4))
        cls.governance = workflow(GOVERNANCE)

    def test_both_formats_and_all_existing_python_inputs_remain_required(self):
        events = children(self.workflow, "on", 2)
        old_events = children(self.python, "on", 2)
        self.assertEqual(set(events), {"push", "pull_request", "workflow_dispatch"})
        self.assertEqual(events["workflow_dispatch"], ("", []))
        self.assertEqual(set(children(events, "push", 4)), {"branches", "paths"})
        self.assertEqual(children(events, "push", 4)["branches"], ("[master]", []))
        self.assertEqual(set(children(events, "pull_request", 4)), {"paths"})
        extra = {".github/workflows/p05-torch.yml", "docs/designs/torch_custom_ops_v1.md",
                 "docs/designs/python_binding_v1.md"}
        for event in ("push", "pull_request"):
            with self.subTest(event=event):
                self.assertLessEqual(path_filters(old_events, event) | extra, path_filters(events, event))
        self.assertEqual(path_filters(events, "push"), path_filters(events, "pull_request"))
        self.assertEqual(set(self.jobs), {"qualification"})
        strategy = children(self.job, "strategy", 6)
        self.assertEqual(strategy["fail-fast"], ("false", []))
        self.assertEqual(strategy["max-parallel"], ("2", []))
        self.assertEqual(scalars(children(strategy, "matrix", 8)), {"format": "[fp16, bf16]"})

    def test_read_only_trust_and_bounded_host_resources(self):
        self.assertEqual(set(self.workflow), {"name", "on", "permissions", "concurrency", "jobs"})
        self.assertEqual(scalars(children(self.workflow, "permissions", 2)), {"contents": "read"})
        self.assertEqual(self.job["runs-on"], ("ubuntu-22.04", []))
        self.assertEqual(self.job["timeout-minutes"], ("120", []))
        self.assertEqual(set(self.job), {
            "name", "runs-on", "timeout-minutes", "strategy", "defaults", "env", "steps",
        })
        self.assertEqual(scalars(children(self.workflow, "concurrency", 2)), {
            "group": "p05-torch-${{ github.event_name }}-${{ github.ref }}", "cancel-in-progress": "false",
        })
        self.assertEqual(scalars(children(children(self.job, "defaults", 6), "run", 8)), {"shell": "bash"})
        self.assertEqual(scalars(children(self.job, "env", 6)), {
            "P05_BACKEND": "simx", "P05_FORMAT": "${{ matrix.format }}",
            "PYTHONDONTWRITEBYTECODE": "'1'", "MAKEFLAGS": "'-j2'", "THREADS": "'2'",
            "CMAKE_BUILD_PARALLEL_LEVEL": "'2'", "CCACHE_DISABLE": "'1'", "OBJCACHE": "''",
        })
        actions = [step["uses"][0] for step in self.steps if "uses" in step]
        self.assertEqual(actions, ["actions/checkout@v4", "actions/setup-python@v5",
                                  "actions/cache/restore@v4", "actions/cache/restore@v4",
                                  "actions/upload-artifact@v4"])
        checkout = next(step for step in self.steps if step.get("uses", (None,))[0] == "actions/checkout@v4")
        self.assertEqual(scalars(children(checkout, "with", 10)), {
            "fetch-depth": "1", "submodules": "recursive", "persist-credentials": "false",
        })
        raw = WORKFLOW.read_text()
        for forbidden in ("pull_request_target", "self-hosted", "secrets.", "actions/cache/save", "write-all"):
            self.assertNotIn(forbidden, raw)

    def test_pinned_prerequisites_and_original_native_commands_are_preserved(self):
        setup = next(step for step in self.steps if step.get("uses", (None,))[0] == "actions/setup-python@v5")
        self.assertEqual(scalars(children(setup, "with", 10)), {
            "python-version": "'3.12.14'", "architecture": "x64", "check-latest": "false",
        })
        pins = tomllib.loads((ROOT / "pyproject.toml").read_text())["build-system"]["requires"]
        self.assertEqual(pins, ["setuptools==84.2.1", "wheel==0.48.0", "packaging==26.3"])
        unchanged = (
            "Provision pinned Python build tools", "Resolve pinned toolchain cache identity",
            "Restore pinned toolchain without writing cache", "Restore dependency inputs without writing cache",
            "Install baseline host dependencies", "Verify clean source and relocate restored tools",
            "Execute unchanged native model reference", "Execute installed Python variant against native results",
        )
        for name in unchanged:
            with self.subTest(step=name):
                self.assertEqual(named(self.steps, name), named(self.python_steps, name))

    def test_framework_download_requires_exact_complete_hash_lock(self):
        provision = named(self.steps, "Provision hash-locked CPU framework wheels")
        self.assertEqual(provision["timeout-minutes"], ("10", []))
        body = script(provision).replace("\\\n", " ").splitlines()
        self.assertEqual(shlex.split(body[0]), ["mkdir", "$P05_ROOT/framework-wheels"])
        self.assertEqual(shlex.split(body[1]), ["cp", "ci/project/p05_torch_contract.json",
                                             "$P05_ROOT/evidence/p05_torch_contract.json"])
        self.assertEqual(shlex.split(body[2]), ["cp", "ci/project/p05_torch_requirements.lock",
                                             "$P05_ROOT/evidence/p05_torch_requirements.lock"])
        self.assertEqual(shlex.split(body[3]), [
            "python3", "-I", "-m", "pip", "--isolated", "download", "--disable-pip-version-check",
            "--no-cache-dir", "--only-binary=:all:", "--no-deps", "--require-hashes",
            "--index-url", "https://download.pytorch.org/whl/cpu",
            "--extra-index-url", "https://pypi.org/simple", "--dest", "$P05_ROOT/framework-wheels",
            "--requirement", "ci/project/p05_torch_requirements.lock",
            "2>&1", "|", "tee", "$P05_ROOT/evidence/framework-provision.log",
        ])
        self.assertEqual(len(body), 4)
        contract = json.loads(CONTRACT.read_text())
        self.assertEqual(contract["framework"]["version"], "2.15.0+cpu")
        self.assertEqual(contract["requirements"], {
            "path": "ci/project/p05_torch_requirements.lock", "sha256": hashlib.sha256(LOCK.read_bytes()).hexdigest(),
        })
        actual = {}
        for line in LOCK.read_text().splitlines():
            if not line or line.startswith("#"):
                continue
            match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s]+) --hash=sha256:([0-9a-f]{64})", line)
            self.assertIsNotNone(match, line)
            normalized = re.sub(r"[-_.]+", "-", match[1]).lower()
            self.assertNotIn(normalized, actual)
            actual[normalized] = (match[2], match[3])
        expected = {re.sub(r"[-_.]+", "-", row["name"]).lower(): (row["version"], row["sha256"])
                    for row in contract["wheels"]}
        self.assertEqual(len(actual), 11)
        self.assertEqual(len(contract["wheels"]), len(expected), "duplicate contract distribution")
        self.assertEqual(actual, expected)
        self.assertEqual(actual["torch"][0], "2.15.0+cpu")
        self.assertEqual(actual["numpy"][0], "2.3.5")
        self.assertFalse(any(name.startswith("nvidia-") for name in actual))

    def test_three_stage_execution_is_sequential_and_no_stage_can_be_skipped(self):
        names = [
            "Verify clean source and relocate restored tools", "Provision hash-locked CPU framework wheels",
            "Execute unchanged native model reference", "Execute installed Python variant against native results",
            "Execute installed PyTorch variant against native results", "Test real PyTorch with scripted native failures",
            "Test compiled native ownership with real PyTorch",
            "Retain native Python and PyTorch execution packets",
        ]
        positions = [self.steps.index(named(self.steps, name)) for name in names]
        self.assertEqual(positions, list(range(8, 16)))
        run = named(self.steps, names[4])
        self.assertEqual(command(run), [
            "python3", "ci/project/p05_torch_execute.py", "run", "--source-dir", "$PWD",
            "--python-work", "$P05_ROOT/work", "--python-output", "$P05_ROOT/evidence/python",
            "--wheelhouse", "$P05_ROOT/framework-wheels", "--work-dir", "$P05_ROOT/torch-work",
            "--output", "$P05_ROOT/evidence/torch", "--format", "$P05_FORMAT",
            "--timeout-seconds", "600", "--run-timeout-seconds", "300",
            "2>&1", "|", "tee", "$P05_ROOT/evidence/torch-execution.log",
        ])
        guarded = {"Install baseline host dependencies", names[-1]}
        for step in self.steps:
            self.assertNotIn("continue-on-error", step)
            self.assertNotIn("shell", step)
            if step.get("name", (None,))[0] not in guarded:
                self.assertNotIn("if", step)
            if "run" in step:
                self.assertNotIn("|| true", script(step))
                self.assertNotIn("--update-baseline", script(step))

    def test_real_torch_failure_suite_is_explicit_and_retained_separately(self):
        host = named(self.steps, "Test real PyTorch with scripted native failures")
        self.assertEqual(host["timeout-minutes"], ("10", []))
        self.assertEqual(command(host), [
            "$P05_ROOT/torch-work/venv/bin/python", "-I", "-B", "ci/project/p05_torch_host_tests.py",
            "--source-dir", "$PWD", "--output", "$P05_ROOT/evidence/torch-host.json",
            "2>&1", "|", "tee", "$P05_ROOT/evidence/torch-host.log",
        ])
        self.assertNotIn("--case", flattened(host))
        upload = named(self.steps, "Retain native Python and PyTorch execution packets")
        self.assertEqual(upload["if"], ("always()", []))
        self.assertEqual(upload["uses"], ("actions/upload-artifact@v4", []))
        self.assertEqual(scalars(children(upload, "with", 10)), {
            "name": "p05-torch-simx-${{ matrix.format }}-${{ github.sha }}-attempt${{ github.run_attempt }}",
            "path": "${{ runner.temp }}/p05-torch/evidence", "if-no-files-found": "error",
            "retention-days": "30", "compression-level": "6", "include-hidden-files": "true",
        })
        identity = script(named(self.steps, "Initialize retained job identity"))
        for token in ("'GITHUB_SHA'", "'GITHUB_RUN_ID'", "'GITHUB_RUN_ATTEMPT'", "'P05_FORMAT'",
                      "scope='simx-installed-pytorch'", "native_execution='not_run'", "python_execution='not_run'",
                      "torch_execution='not_run'", "acceptance_claimed=False", "'workflow.yml'"):
            self.assertIn(token, identity)

    def test_compiled_host_runtime_is_explicit_bounded_and_retained_separately(self):
        host = named(self.steps, "Test compiled native ownership with real PyTorch")
        self.assertEqual(host["timeout-minutes"], ("20", []))
        self.assertEqual(command(host), [
            "$P05_ROOT/torch-work/venv/bin/python", "-I", "-B", "ci/project/p05_torch_native_host_tests.py",
            "--source-dir", "$PWD", "--work-dir", "$P05_ROOT/evidence/torch-native-host",
            "--format", "$P05_FORMAT",
            "2>&1", "|", "tee", "$P05_ROOT/evidence/torch-native-host.log",
        ])
        self.assertNotIn("--bundle", flattened(host))
        self.assertNotIn("if", host)

    def test_compiled_host_failure_propagates_and_preserves_raw_log(self):
        bash = shutil.which("bash")
        self.assertIsNotNone(bash)
        with tempfile.TemporaryDirectory(prefix="p05-compiled-host-workflow-") as directory:
            root = Path(directory)
            (root / "evidence").mkdir()
            stub = root / "torch-work/venv/bin/python"
            stub.parent.mkdir(parents=True)
            stub.write_text("#!/bin/sh\nprintf '%s\\n' 'injected compiled host failure'\nexit 23\n")
            stub.chmod(0o700)
            env = {"PATH": os.defpath, "P05_ROOT": str(root), "P05_FORMAT": "bf16"}
            body = script(named(self.steps, "Test compiled native ownership with real PyTorch"))
            result = subprocess.run([bash, "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", body],
                                    cwd=root, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
            self.assertEqual((root / "evidence/torch-native-host.log").read_text(),
                             "injected compiled host failure\n")

    def test_shell_pipeline_propagates_runner_failure_and_preserves_raw_log(self):
        bash = shutil.which("bash")
        self.assertIsNotNone(bash, "workflow contract requires bash")
        with tempfile.TemporaryDirectory(prefix="p05-torch-workflow-") as directory:
            root = Path(directory)
            (root / "evidence").mkdir()
            tools = root / "bin"
            tools.mkdir()
            stub = tools / "python3"
            stub.write_text("#!/bin/sh\nprintf '%s\\n' 'injected runner failure'\nexit 23\n")
            stub.chmod(0o700)
            env = {"PATH": str(tools) + os.pathsep + os.defpath,
                   "P05_ROOT": str(root), "P05_FORMAT": "fp16"}
            body = script(named(self.steps, "Execute installed PyTorch variant against native results"))
            result = subprocess.run([bash, "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", body],
                                    cwd=root, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
            self.assertEqual((root / "evidence/torch-execution.log").read_text(), "injected runner failure\n")

    def test_governance_covers_new_contract_without_replacing_existing_gates(self):
        events = children(self.governance, "on", 2)
        for event in ("push", "pull_request"):
            with self.subTest(event=event):
                self.assertLessEqual({".github/workflows/p05-torch.yml", "docs/designs/torch_custom_ops_v1.md",
                                      "python/**", "ci/project/**"}, path_filters(events, event))
        job = children(children(self.governance, "jobs", 2), "governance", 4)
        commands = [script(step) for step in steps(job) if "run" in step]
        for required in ("python3 ci/project/check_project.py", "python3 ci/project/check_baseline_packets.py",
                         "python3 -m unittest discover -s ci/project -p 'test_*.py'"):
            self.assertIn(required, commands)
        self.assertEqual(len(commands), 5)


if __name__ == "__main__":
    unittest.main()
