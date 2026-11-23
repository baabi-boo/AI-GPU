# SPDX-License-Identifier: Apache-2.0
"""Host checks for fresh-dependency workflow boundaries and failure retention."""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import p06_dependency_contract as contract
import p06_managed_preflight_execute as preflight
import p06_pending_probe as probe
from test_p05_ci_workflow import children, path_filters, scalars, script, steps, workflow
from test_p06_managed_preflight_ci import host_environment, python_body, required_sources
from test_p06_workspace_ci import covers, one_command


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/p06-dependency-provenance.yml"
INITIALIZE = "Initialize retained job identity and resource observations"
INTERPRETER = "Retain and verify Python interpreter identity"
PREPARE = "Verify clean source and acquire pinned dependency objects"
BUILD = "Build and retain fresh selected dependency products"
PIN = "Pin the original dependency receipt"
EXECUTE = "Execute all managed lifetime processes serially"
PROBE = "Observe native pending reads and reject the always-zero control"
CONTROL = "Reject a fresh alternate dependency after correct numerical output"


class DependencyWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = workflow(WORKFLOW)
        cls.events = children(cls.workflow, "on", 2)
        cls.jobs = children(cls.workflow, "jobs", 2)
        cls.job = children(cls.jobs, "dependency-provenance", 4)
        cls.steps = steps(cls.job)

    def one(self, key, value):
        selected = [step for step in self.steps if step.get(key, (None,))[0] == value]
        self.assertEqual(len(selected), 1, (key, value))
        return selected[0]

    def test_triggers_cover_dependency_native_probe_and_governance_inputs(self):
        self.assertEqual(set(self.events), {"push", "pull_request", "workflow_dispatch"})
        self.assertEqual(self.events["workflow_dispatch"], ("", []))
        self.assertEqual(children(self.events, "push", 4)["branches"], ("[master]", []))
        self.assertEqual(path_filters(self.events, "push"), path_filters(self.events, "pull_request"))
        new_names = set(probe.SOURCE_FILES) | {
            WORKFLOW.relative_to(ROOT).as_posix(), "docs/designs/dependency_provenance_v1.md",
            "tests/regression/ai_counter_preflight/dependency_model.mk"}
        new_names.update(path.relative_to(ROOT).as_posix()
                         for path in (ROOT / "ci/project").glob("*dependency*.py"))
        governance = children(workflow(ROOT / ".github/workflows/project-governance.yml"), "on", 2)
        for event in ("push", "pull_request"):
            for label, events, names in (("dependency", self.events, required_sources() | new_names),
                                         ("governance", governance, new_names)):
                with self.subTest(event=event, workflow=label):
                    patterns = path_filters(events, event)
                    self.assertEqual(sorted(name for name in names if not covers(patterns, name)), [])

    def test_single_worker_fixed_budget_and_read_only_authority(self):
        self.assertEqual(set(self.jobs), {"dependency-provenance"})
        self.assertEqual(self.job["runs-on"], ("ubuntu-22.04", []))
        self.assertEqual(self.job["timeout-minutes"], ("90", []))
        self.assertNotIn("strategy", self.job)
        self.assertEqual(scalars(children(self.workflow, "permissions", 2)), {"contents": "read"})
        self.assertEqual(children(self.workflow, "concurrency", 2)["cancel-in-progress"], ("false", []))
        self.assertEqual(scalars(children(self.job, "env", 6)), {
            "PYTHONDONTWRITEBYTECODE": "'1'", "MAKEFLAGS": "'-j2'", "THREADS": "'1'",
            "CMAKE_BUILD_PARALLEL_LEVEL": "'2'", "CCACHE_DISABLE": "'1'", "OBJCACHE": "''"})
        self.assertEqual({name: contract.BUDGET[name] for name in preflight.BUDGET}, preflight.BUDGET)
        self.assertEqual((contract.BUDGET["jobs"], contract.BUDGET["simulation_workers"]), (2, 1))
        self.assertNotRegex(WORKFLOW.read_text(),
            r"secrets\s*\.|pull_request_target|workflow_run|write-all|id-token:|continue-on-error|self-hosted|matrix\.")
        for step in self.steps:
            if "if" in step:
                self.assertIn(step, [self.one("name", "Install baseline host dependencies"),
                                     self.one("uses", "actions/upload-artifact@v4")])
            if "run" in step:
                self.assertNotRegex(script(step), r"\|\|\s*true|set\s+\+|(?:^|\s)exit\s+0|git\s+push|gh\s+")
            if "env" in step:
                self.assertNotIn("THREADS", children(step, "env", 10))

    def test_fresh_checkout_restores_only_the_pinned_toolchain(self):
        self.assertEqual(scalars(children(self.one("uses", "actions/checkout@v4"), "with", 10)), {
            "fetch-depth": "1", "submodules": "recursive", "persist-credentials": "false"})
        caches = [step for step in self.steps if step.get("uses", ("",))[0].startswith("actions/cache")]
        self.assertEqual(len(caches), 1)
        self.assertEqual(caches[0]["uses"], ("actions/cache/restore@v4", []))
        config = scalars(children(caches[0], "with", 10))
        self.assertEqual(config, {"path": "tools",
            "key": "${{ runner.os }}-toolchain-${{ steps.pins.outputs.toolchain }}-lite",
            "restore-keys": "${{ runner.os }}-toolchain-${{ steps.pins.outputs.toolchain }}-"})
        self.assertEqual(self.one("name", "Install baseline host dependencies")["if"],
                         ("steps.toolchain.outputs.cache-matched-key != ''", []))
        self.assertNotIn("P06_DEPENDENCY_CACHE", WORKFLOW.read_text())
        self.assertNotIn("p04_ci_prepare.py", WORKFLOW.read_text())

    def test_actual_resource_guard_retains_failure_identity_before_cache(self):
        body = python_body(self.one("name", INITIALIZE))
        for disk, memory, passed in ((15 * 2**30, 4 * 2**30, True),
                                    (15 * 2**30 - 1, 4 * 2**30, False),
                                    (15 * 2**30, 4 * 2**30 - 1, False),
                                    (15 * 2**30, None, False)):
            with self.subTest(disk=disk, memory=memory), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                setup = ("import shutil, sys\nfrom types import SimpleNamespace\n"
                    f"sys.path.insert(0, {str(ROOT / 'ci/project')!r})\nimport preflight\n"
                    f"shutil.disk_usage = lambda path: SimpleNamespace(free={disk!r})\n"
                    f"preflight.available_memory_bytes = lambda: {memory!r}\n"
                    f"exec(compile({body!r}, 'dependency-workflow-init', 'exec'))\n")
                environment = dict(host_environment(root), GITHUB_JOB="dependency-provenance")
                result = subprocess.run([sys.executable, "-c", setup], cwd=ROOT, env=environment,
                    text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode == 0, passed, result.stderr)
                evidence = root / "p06-dependency-provenance/evidence"
                receipt = json.loads((evidence / "job.json").read_text())
                self.assertEqual(receipt["contract_id"], contract.MANAGED_CONTRACT_ID)
                self.assertEqual(receipt["free_disk_bytes_before_cache"], disk)
                self.assertEqual(receipt["available_memory_bytes_before_cache"], memory)
                self.assertEqual(receipt["native_execution"], "not_run")
                for name in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB",
                             "GITHUB_EVENT_NAME", "GITHUB_REPOSITORY", "GITHUB_REF"):
                    self.assertEqual(receipt[name], environment[name])
                for name in (*contract.FALSE_CLAIMS, "native_preflight_passed", "native_lifetime_passed",
                             "fresh_dependency_build_passed", "dependency_source_to_loaded_binary_verified"):
                    self.assertIs(receipt[name], False)
                self.assertEqual((evidence / "workflow.yml").read_bytes(), WORKFLOW.read_bytes())
                self.assertEqual(receipt["workflow_sha256"], hashlib.sha256(WORKFLOW.read_bytes()).hexdigest())
                self.assertEqual((root / "environment").read_text(),
                                 "P06_DEPENDENCY_ROOT=" + str(root / "p06-dependency-provenance") + "\n")

    def test_python_pin_and_pipeline_order_precede_native_execution(self):
        provision = self.one("uses", "actions/setup-python@v5")
        self.assertEqual(scalars(children(provision, "with", 10)), {
            "python-version": "'3.12.14'", "architecture": "x64", "check-latest": "false"})
        ordered = [self.one("uses", "actions/checkout@v4"), self.one("name", INITIALIZE), provision,
            self.one("name", INTERPRETER), self.one("id", "toolchain"),
            self.one("name", "Install baseline host dependencies"),
            *(self.one("name", name) for name in (PREPARE, BUILD, PIN, EXECUTE, PROBE, CONTROL)),
            self.one("uses", "actions/upload-artifact@v4")]
        indices = [self.steps.index(step) for step in ordered]
        self.assertEqual(indices, sorted(indices))
        for name in (PREPARE, BUILD, PIN, EXECUTE, PROBE, CONTROL):
            self.assertNotIn("if", self.one("name", name))

    def test_actual_cli_parsers_agree_on_source_workspace_and_receipt(self):
        import p06_dependency_build as builder
        import p06_dependency_prepare as prepare
        import p06_dependency_lifetime_execute as runner
        import p06_dependency_substitution as substitution
        prepared = one_command(self.one("name", PREPARE), pipefail=True)
        built = one_command(self.one("name", BUILD), pipefail=True)
        self.assertEqual(prepared[:2], ["python3", "ci/project/p06_dependency_prepare.py"])
        self.assertEqual(built[:2], ["python3", "ci/project/p06_dependency_build.py"])
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(prepare, "prepare",
                return_value={"outcome": "pass", "reason": None, "dependency_cache_used": False}) as call:
            self.assertEqual(prepare.main(prepared[2:prepared.index("2>&1")]), 0)
            preparation = call.call_args.args[0]
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(builder, "build",
                return_value={"outcome": "pass", "reason": None, "fresh_dependency_build_passed": True}) as call:
            self.assertEqual(builder.main(built[2:built.index("2>&1")]), 0)
            build = call.call_args.args[0]
        native = one_command(self.one("name", EXECUTE), pipefail=True)
        self.assertEqual(native[:3], ["python3", "ci/project/p06_dependency_lifetime_execute.py", "run"])
        run = runner.argument_parser().parse_args(native[2:native.index("2>&1")])
        pending = one_command(self.one("name", PROBE), pipefail=True)
        probe_args = probe.argument_parser().parse_args(pending[2:pending.index("2>&1")])
        alternate = one_command(self.one("name", CONTROL), pipefail=True)
        self.assertEqual(alternate[:2], ["python3", "ci/project/p06_dependency_substitution.py"])
        control_args = substitution.argument_parser().parse_args(alternate[2:alternate.index("2>&1")])
        self.assertEqual(preparation.workspace_dir, Path("$P06_DEPENDENCY_ROOT"))
        self.assertEqual(build.workspace_dir, preparation.workspace_dir)
        self.assertEqual(build.preparation, preparation.workspace_dir / "evidence/dependency-preparation.json")
        self.assertEqual(build.output_dir, preparation.workspace_dir / "evidence/dependency-build")
        self.assertEqual(run.dependency_receipt, build.output_dir / "report.json")
        self.assertEqual(run.tools_dir, preparation.workspace_dir / "tools")
        self.assertEqual(run.work_dir, preparation.workspace_dir / "work")
        self.assertEqual((run.mode, run.jobs, run.timeout_seconds, run.run_timeout_seconds), ("run", 2, 1800, 180))
        self.assertEqual(run.dependency_receipt_sha256, "$P06_DEPENDENCY_RECEIPT_SHA256")
        self.assertEqual(probe_args.dependency_receipt_sha256, run.dependency_receipt_sha256)
        self.assertEqual(probe_args.managed_report, run.output / "report.json")
        self.assertEqual(probe_args.build_dir, run.work_dir / "simx-fp16")
        self.assertEqual(control_args.dependency_receipt, run.dependency_receipt)
        self.assertEqual(control_args.dependency_receipt_sha256, run.dependency_receipt_sha256)
        self.assertEqual(control_args.managed_report, probe_args.managed_report)
        self.assertEqual(control_args.build_dir, probe_args.build_dir)
        self.assertEqual(control_args.output_dir,
                         preparation.workspace_dir / "evidence/dependency-substitution")
        self.assertNotEqual(control_args.output_dir, probe_args.output_dir)
        for args in (preparation, build, run, probe_args, control_args):
            self.assertEqual(args.source_dir, Path("$PWD"))
            self.assertEqual(args.expected_revision, "$GITHUB_SHA")

    def pin_receipt(self, payload):
        temporary = tempfile.TemporaryDirectory(prefix="dependency-ci-receipt-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        target = root / "evidence/dependency-build/report.json"
        target.parent.mkdir(parents=True)
        target.write_bytes(payload)
        environment = dict(host_environment(root), P06_DEPENDENCY_ROOT=str(root))
        result = subprocess.run([sys.executable, "-c", python_body(self.one("name", PIN))],
            cwd=ROOT, env=environment, text=True, capture_output=True, timeout=10)
        self.assertEqual(target.read_bytes(), payload)
        return root, result

    def test_receipt_pin_is_the_exact_original_bytes_and_not_a_favorable_label(self):
        document = {"schema_version": 1, "contract_id": contract.CONTRACT_ID,
            "state": "finished", "outcome": "pass", "fresh_dependency_build_passed": True,
            "expected_revision": "1" * 40, **dict.fromkeys(contract.FALSE_CLAIMS, False)}
        payload = (json.dumps(document, indent=3) + "\n").encode()
        root, result = self.pin_receipt(payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        digest = hashlib.sha256(payload).hexdigest()
        self.assertEqual((root / "environment").read_text(), "P06_DEPENDENCY_RECEIPT_SHA256=" + digest + "\n")
        identity = json.loads((root / "evidence/dependency-receipt.json").read_text())
        self.assertEqual(identity, {"path": "dependency-build/report.json", "sha256": digest,
            "size_bytes": len(payload), "expected_revision": "1" * 40})
        changes = [("schema_version", True), ("contract_id", contract.MANAGED_CONTRACT_ID),
            ("state", "running"), ("outcome", "fail"), ("fresh_dependency_build_passed", 1),
            ("expected_revision", "2" * 40), *((name, True) for name in contract.FALSE_CLAIMS)]
        rejected = [json.dumps(dict(document, **{name: value})).encode() for name, value in changes]
        rejected.extend([b'{}', b'[]', b'{"outcome":"fail","outcome":"pass"}',
                         b'{"value":NaN}', b" " * (contract.MAX_RECEIPT_BYTES + 1)])
        for payload in rejected:
            with self.subTest(payload=payload[:100]):
                root, result = self.pin_receipt(payload)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root / "environment").exists())
                self.assertFalse((root / "evidence/dependency-receipt.json").exists())

    def test_failed_producers_retain_original_stdout_stderr_and_status(self):
        for name, log, executable in ((PREPARE, "preparation.log", "python3"),
                (BUILD, "dependency-build.log", "python3"), (EXECUTE, "execution.log", "python3"),
                (PROBE, "pending-probe.log", "python3"),
                (CONTROL, "dependency-substitution.log", "python3"),
                ("Install baseline host dependencies", "host-dependencies.log", "sudo")):
            with self.subTest(step=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "evidence").mkdir()
                stub = root / executable
                stub.write_text('#!/bin/sh\nprintf "original stdout\\n"\n'
                                'printf "original stderr\\n" >&2\nexit 37\n')
                stub.chmod(0o700)
                environment = dict(host_environment(root), PATH=str(root) + os.pathsep + os.defpath,
                    P06_DEPENDENCY_ROOT=str(root), P06_DEPENDENCY_TOOLCHAIN_ID="unused",
                    P06_DEPENDENCY_TOOLCHAIN_CACHE="unused", P06_DEPENDENCY_RECEIPT_SHA256="d" * 64)
                result = subprocess.run(["/bin/bash", "-c", script(self.one("name", name))],
                    cwd=ROOT, env=environment, text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 37, result.stderr)
                self.assertEqual((root / "evidence" / log).read_text(), "original stdout\noriginal stderr\n")

    def test_shell_python_and_always_retained_artifact_boundary(self):
        for step in self.steps:
            if "run" in step:
                with self.subTest(step=step.get("name")):
                    result = subprocess.run(["/bin/bash", "-n"], input=script(step),
                        text=True, capture_output=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    if "<<'PY'" in script(step):
                        compile(python_body(step, isolated=step == self.one("name", INTERPRETER)),
                                str(WORKFLOW), "exec")
        upload = self.one("uses", "actions/upload-artifact@v4")
        self.assertEqual(upload["if"], ("always()", []))
        self.assertEqual(self.steps[-1], upload)
        config = scalars(children(upload, "with", 10))
        self.assertEqual(config, {
            "name": "p06-dependency-provenance-${{ github.sha }}-run${{ github.run_id }}-attempt${{ github.run_attempt }}",
            "path": "${{ runner.temp }}/p06-dependency-provenance/evidence",
            "if-no-files-found": "error", "retention-days": "30", "compression-level": "6",
            "include-hidden-files": "true"})


if __name__ == "__main__":
    unittest.main()
