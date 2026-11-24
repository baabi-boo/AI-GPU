# SPDX-License-Identifier: Apache-2.0
"""Check the original native workflow as data and unchanged native build entry.

The current workflow performs historical replay and is covered separately by
``test_p06_replay_ci``. No archived Python or native command is executed here.
"""

from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

from baseline_inventory import SOURCE_INPUTS
from governance_workflow_test_support import assert_strict_governance_step
import p03_execute
import p04_ci_prepare
import p06_execute as runner
from p06_contract import load_analysis_contract
from p06_test_frozen_sources import frozen_source_bytes
from test_p05_ci_workflow import (children, command, path_filters, scalars,
                                  script, steps, workflow)


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ".github/workflows/p06-baseline.yml"
GOVERNANCE = ROOT / ".github/workflows/project-governance.yml"


def covers(patterns, path):
    for pattern in patterns:
        expression = re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
        if re.fullmatch(expression, path):
            return True
    return False


def required_sources():
    names = set(SOURCE_INPUTS + runner.SOURCE_FILES + runner.base.COPIED
                + runner.base.TOOLING + runner.base.CORPUS
                + runner.model_run.SOURCE_FILES + p03_execute.SOURCE_FILES)
    names.update(row["path"] for row in load_analysis_contract()["source_inputs"])
    names.update(row["path"] for row in runner.LOADED_HELPERS)
    for directory in runner.base.SOURCE_ROOTS:
        names.update(path.relative_to(ROOT).as_posix()
                     for path in (ROOT / directory).rglob("*")
                     if path.is_file() and (path.suffix in runner.base.SOURCE_SUFFIXES
                                            or path.name == "Makefile"))
    names.update({"Makefile.in", "config.mk.in", "ci/toolchain_rev.sh",
                  "ci/install_dependencies.sh", "third_party/Makefile",
                  "profiles/p02-tfr.json", "docs/designs/native_benchmark_v1.md",
                  Path(__file__).relative_to(ROOT).as_posix()})
    return names


class HistoricalNativeBaselineWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="p06-historical-workflow-")
        cls.addClassCleanup(temporary.cleanup)
        cls.workflow_path = Path(temporary.name) / "p06-baseline.yml"
        cls.workflow_path.write_bytes(frozen_source_bytes(WORKFLOW_PATH))
        cls.workflow = workflow(cls.workflow_path)
        cls.events = children(cls.workflow, "on", 2)
        cls.jobs = children(cls.workflow, "jobs", 2)
        cls.job = children(cls.jobs, "baseline", 4)
        cls.steps = steps(cls.job)
        p04 = workflow(ROOT / ".github/workflows/p04-model.yml")
        cls.p04_steps = steps(children(children(p04, "jobs", 2), "qualification", 4))

    def one(self, key, value, sequence=None):
        selected = self.steps if sequence is None else sequence
        found = [step for step in selected if step.get(key, (None,))[0] == value]
        self.assertEqual(len(found), 1, (key, value))
        return found[0]

    def test_only_master_push_pull_request_and_manual_events_are_exposed(self):
        self.assertEqual(set(self.workflow), {"name", "on", "permissions", "concurrency", "jobs"})
        self.assertEqual(set(self.events), {"push", "pull_request", "workflow_dispatch"})
        self.assertEqual(self.events["workflow_dispatch"], ("", []))
        push = children(self.events, "push", 4)
        self.assertEqual(set(push), {"branches", "paths"})
        self.assertEqual(push["branches"], ("[master]", []))
        self.assertEqual(set(children(self.events, "pull_request", 4)), {"paths"})
        self.assertEqual(path_filters(self.events, "push"), path_filters(self.events, "pull_request"))

    def test_all_bound_sources_and_build_inputs_trigger_both_events(self):
        for event in ("push", "pull_request"):
            patterns = path_filters(self.events, event)
            for path in sorted(required_sources()):
                with self.subTest(event=event, path=path):
                    self.assertTrue(covers(patterns, path), "uncovered retained input: " + path)

    def test_reconstructed_missing_transitive_input_is_detected(self):
        for event in ("push", "pull_request"):
            patterns = path_filters(self.events, event)
            self.assertIn("ci/blackbox.sh", SOURCE_INPUTS)
            self.assertTrue(covers(patterns, "ci/blackbox.sh"))
            without = patterns - {"ci/blackbox.sh"}
            self.assertFalse(covers(without, "ci/blackbox.sh"))

    def test_hosted_simx_matrix_and_resource_limits_match_the_frozen_budget(self):
        self.assertEqual(set(self.jobs), {"baseline"})
        self.assertEqual(set(self.job), {
            "name", "runs-on", "timeout-minutes", "strategy", "defaults", "env", "steps",
        })
        self.assertEqual(self.job["runs-on"], ("ubuntu-22.04", []))
        self.assertEqual(self.job["timeout-minutes"], ("90", []))
        strategy = children(self.job, "strategy", 6)
        self.assertEqual(set(strategy), {"fail-fast", "max-parallel", "matrix"})
        self.assertEqual(strategy["fail-fast"], ("false", []))
        self.assertEqual(strategy["max-parallel"], ("2", []))
        self.assertEqual(scalars(children(strategy, "matrix", 8)), {"format": "[fp16, bf16]"})
        self.assertEqual(scalars(children(self.job, "env", 6)), {
            "P06_BACKEND": "simx", "P06_FORMAT": "${{ matrix.format }}",
            "PYTHONDONTWRITEBYTECODE": "'1'", "MAKEFLAGS": "'-j2'", "THREADS": "'2'",
            "CMAKE_BUILD_PARALLEL_LEVEL": "'2'", "CCACHE_DISABLE": "'1'", "OBJCACHE": "''",
        })
        defaults = children(self.job, "defaults", 6)
        self.assertEqual(set(defaults), {"run"})
        self.assertEqual(scalars(children(defaults, "run", 8)), {"shell": "bash"})
        expected = {"min_free_bytes": 15 * 1024**3, "max_rss_bytes": 4 * 1024**3,
                    "max_log_bytes": 16 * 1024**2}
        self.assertEqual(runner.BUDGET, expected)
        self.assertEqual((p04_ci_prepare.MIN_FREE_BYTES, p04_ci_prepare.MAX_RSS_BYTES),
                         (expected["min_free_bytes"], expected["max_rss_bytes"]))
        self.assertEqual(load_analysis_contract()["budget"], dict(expected, jobs_max=2,
                         build_timeout_seconds=1800, run_timeout_seconds=180))

    def test_token_checkout_actions_and_step_controls_keep_the_trust_boundary(self):
        self.assertEqual(scalars(children(self.workflow, "permissions", 2)), {"contents": "read"})
        self.assertEqual(scalars(children(self.workflow, "concurrency", 2)), {
            "group": "p06-baseline-${{ github.event_name }}-${{ github.ref }}",
            "cancel-in-progress": "false",
        })
        checkout = self.one("uses", "actions/checkout@v4")
        self.assertEqual(set(checkout), {"uses", "with"})
        self.assertEqual(scalars(children(checkout, "with", 10)), {
            "fetch-depth": "1", "submodules": "recursive", "persist-credentials": "false",
        })
        self.assertEqual([step["uses"][0] for step in self.steps if "uses" in step], [
            "actions/checkout@v4", "actions/setup-python@v5", "actions/cache/restore@v4",
            "actions/cache/restore@v4", "actions/upload-artifact@v4",
        ])
        for step in self.steps:
            self.assertTrue(set(step) <= {"name", "uses", "with", "run", "id", "if", "env", "timeout-minutes"})
            self.assertNotIn("continue-on-error", step)
            if "if" in step:
                self.assertIn(step, [self.one("name", "Install baseline host dependencies"),
                                     self.one("uses", "actions/upload-artifact@v4")])
        self.assertNotRegex(self.workflow_path.read_text(), r"secrets\s*\.|pull_request_target|self-hosted|write-all|id-token:")

    def test_pinned_python_and_its_identity_probe_precede_preparation(self):
        setup = self.one("uses", "actions/setup-python@v5")
        self.assertEqual(scalars(children(setup, "with", 10)), {
            "python-version": "'3.12.14'", "architecture": "x64", "check-latest": "false",
        })
        probe = self.one("name", "Retain and verify Python interpreter identity")
        body = script(probe)
        for token in ("'python-provision.json'", "data['python_version'] != [3, 12, 14]",
                      "data['implementation'] != 'CPython'", "data['platform'] != 'linux'",
                      "Path(data['python3_on_path']).resolve() != Path(sys.executable).resolve()",
                      "raise SystemExit("):
            self.assertIn(token, body)
        order = [self.one("uses", "actions/checkout@v4"),
                 self.one("name", "Initialize retained job identity"), setup, probe,
                 self.one("name", "Install baseline host dependencies"),
                 self.one("name", "Verify clean source and relocate restored tools"),
                 self.one("name", "Execute frozen native baseline workloads"),
                 self.one("uses", "actions/upload-artifact@v4")]
        self.assertEqual([self.steps.index(step) for step in order],
                         sorted(self.steps.index(step) for step in order))

    def test_restore_only_caches_bind_the_existing_native_preparation_identity(self):
        for identifier in ("toolchain", "dependencies"):
            self.assertEqual(self.one("id", identifier), self.one("id", identifier, self.p04_steps))
        pins = script(self.one("id", "pins")).replace("P06_", "P04_")
        self.assertEqual(pins, script(self.one("id", "pins", self.p04_steps)))
        self.assertLess(self.steps.index(self.one("id", "pins")),
                        self.steps.index(self.one("id", "toolchain")))
        install = self.one("name", "Install baseline host dependencies")
        self.assertEqual(install["if"], (
            "steps.toolchain.outputs.cache-matched-key != '' && steps.dependencies.outputs.cache-matched-key != ''", []))
        self.assertEqual(install["timeout-minutes"], ("15", []))
        self.assertEqual(command(install), ["sudo", "bash", "ci/install_dependencies.sh", "2>&1",
                                           "|", "tee", "$P06_ROOT/evidence/host-dependencies.log"])
        for step in self.steps:
            if "run" in step:
                self.assertNotRegex(script(step), r"toolchain_install|(?:curl|wget)\s|make\s.*third_party|git clone")

    def test_preparation_and_execution_use_bounded_fresh_paths_and_propagate_status(self):
        prepare = self.one("name", "Verify clean source and relocate restored tools")
        self.assertEqual(set(prepare), {"name", "env", "run"})
        self.assertEqual(scalars(children(prepare, "env", 10)), {
            "P06_TOOLCHAIN_ID": "${{ steps.pins.outputs.toolchain }}",
            "P06_TOOLCHAIN_CACHE": "${{ steps.toolchain.outputs.cache-matched-key }}",
            "P06_DEPENDENCY_CACHE": "${{ steps.dependencies.outputs.cache-matched-key }}",
            "P06_DEPENDENCY_KEY": "${{ runner.os }}-thirdparty-${{ hashFiles('third_party/Makefile', '.gitmodules') }}",
        })
        self.assertEqual(command(prepare), [
            "python3", "ci/project/p04_ci_prepare.py", "--source-dir", "$PWD",
            "--workspace-dir", "$P06_ROOT", "--expected-revision", "$GITHUB_SHA",
            "--toolchain-id", "$P06_TOOLCHAIN_ID", "--toolchain-cache-key", "$P06_TOOLCHAIN_CACHE",
            "--third-party-cache-key", "$P06_DEPENDENCY_CACHE", "--expected-third-party-key",
            "$P06_DEPENDENCY_KEY", "--backend", "$P06_BACKEND", "--format", "$P06_FORMAT",
            "2>&1", "|", "tee", "$P06_ROOT/evidence/preparation.log",
        ])
        execute = self.one("name", "Execute frozen native baseline workloads")
        self.assertEqual(set(execute), {"name", "run"})
        self.assertEqual(command(execute), [
            "python3", "ci/project/p06_execute.py", "run", "--source-dir", "$PWD",
            "--tools-dir", "$P06_ROOT/tools", "--work-dir", "$P06_ROOT/work",
            "--output", "$P06_ROOT/evidence/baseline", "--format", "$P06_FORMAT", "--jobs", "2",
            "--timeout-seconds", "1800", "--run-timeout-seconds", "180",
            "2>&1", "|", "tee", "$P06_ROOT/evidence/execution.log",
        ])
        for step in (prepare, execute):
            self.assertEqual(len(script(step).replace("\\\n", " ").splitlines()), 1)
            self.assertNotIn("--development", command(step))
            self.assertNotRegex(script(step), r"\|\|\s*true|set\s+\+|;|(?:^|\s)exit\s+0")

    def test_failure_packet_upload_is_complete_and_uniquely_named(self):
        upload = self.one("uses", "actions/upload-artifact@v4")
        self.assertEqual(upload["if"], ("always()", []))
        self.assertEqual(set(upload), {"name", "if", "uses", "with"})
        self.assertEqual(scalars(children(upload, "with", 10)), {
            "name": "p06-simx-${{ matrix.format }}-${{ github.sha }}-run${{ github.run_id }}-attempt${{ github.run_attempt }}",
            "path": "${{ runner.temp }}/p06-baseline/evidence", "if-no-files-found": "error",
            "retention-days": "30", "compression-level": "6", "include-hidden-files": "true",
        })
        self.assertEqual(self.steps[-1], upload)

    def test_historical_identity_block_declares_retention_without_execution(self):
        # Inspect pinned historical source as data. The replacement current
        # replay identity block gets an actual host execution in its own suite.
        body = script(self.one("name", "Initialize retained job identity"))
        lines = body.splitlines()
        self.assertEqual(lines[0], "python3 - <<'PY'")
        self.assertEqual(lines[-1], "PY")
        for token in ("Path('.github/workflows/p06-baseline.yml').read_bytes()",
                      "(root / 'evidence' / 'workflow.yml').write_bytes(workflow)",
                      "'GITHUB_SHA'", "'GITHUB_EVENT_NAME'", "'GITHUB_RUN_ID'",
                      "'GITHUB_RUN_ATTEMPT'", "'GITHUB_JOB'", "'GITHUB_REPOSITORY'",
                      "'GITHUB_REF'", "'P06_BACKEND'", "'P06_FORMAT'",
                      "scope='simx-native-baseline'", "native_execution='not_run'",
                      "acceptance_claimed=False",
                      "workflow_sha256=hashlib.sha256(workflow).hexdigest()",
                      "(root / 'evidence' / 'job.json').write_text(",
                      "environment.write('P06_ROOT=' + str(root)"):
            self.assertIn(token, body)
        self.assertEqual(self.workflow_path.read_bytes(), frozen_source_bytes(WORKFLOW_PATH))

    def test_every_shell_block_is_syntactically_valid_without_execution(self):
        for step in self.steps:
            if "run" in step:
                with self.subTest(step=step.get("name", step.get("id"))):
                    result = subprocess.run(["bash", "-n"], input=script(step), text=True,
                                            capture_output=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_governance_covers_new_inputs_and_keeps_existing_checks_unconditional(self):
        governance = workflow(GOVERNANCE)
        events = children(governance, "on", 2)
        required = set(runner.SOURCE_FILES) - {".github/workflows/p04-model.yml"}
        required = {name for name in required if not name.startswith("tests/regression/")} | {
            "tests/regression/ai_bench_common/observer.cpp", "tests/regression/ai_bench_common/counters.h",
            "tests/regression/ai_bench_matmul/Makefile", "tests/regression/ai_bench_mlp/Makefile",
            "docs/designs/native_benchmark_v1.md", Path(__file__).relative_to(ROOT).as_posix(),
        }
        for event in ("push", "pull_request"):
            patterns = path_filters(events, event)
            for path in required:
                self.assertTrue(covers(patterns, path), (event, path))
        job = children(children(governance, "jobs", 2), "governance", 4)
        self.assertEqual(set(job), {"runs-on", "timeout-minutes", "env", "steps"})
        self.assertEqual(job["runs-on"], ("ubuntu-24.04", []))
        self.assertEqual(job["timeout-minutes"], ("90", []))
        self.assertEqual(scalars(children(job, "env", 6)), {
            "PYTHONDONTWRITEBYTECODE": "'1'",
            "GOVERNANCE_ROOT": "${{ runner.temp }}/project-governance",
        })
        checks = {"Inspect governance prerequisites": "python3 ci/project/preflight.py --tier governance",
                  "Validate project structure and evidence": "python3 ci/project/check_project.py",
                  "Check published baseline packet consistency": "python3 ci/project/check_baseline_packets.py"}
        governance_steps = steps(job)
        for name, expected in checks.items():
            step = self.one("name", name, governance_steps)
            self.assertEqual(set(step), {"name", "run"})
            self.assertEqual(script(step), expected)
        assert_strict_governance_step(self, self.one("name", "Test governance tooling", governance_steps))
        upload = self.one("uses", "actions/upload-artifact@v4", governance_steps)
        self.assertEqual(set(upload), {"name", "if", "uses", "with"})
        self.assertEqual(upload["if"], ("always()", []))
        self.assertEqual(governance_steps[-1], upload)


class NativeBaselineBuildEntryTests(unittest.TestCase):
    def test_benchmark_apps_compile_original_sources_and_only_observe_device_lifetime(self):
        base_sources = ["$(SRC_DIR)/main.cpp", "$(AI_DIR)/contract.cpp", "$(AI_DIR)/runtime.cpp"]
        for kind, app in runner.APPS.items():
            with self.subTest(kind=kind):
                text = (ROOT / app / "Makefile").read_text().replace("\\\n", " ")
                values = {}
                for line in text.splitlines():
                    match = re.fullmatch(r"([A-Z_]+)\s*(:=|\+=)\s*(.*)", line)
                    if match:
                        self.assertNotIn(match[1], values)
                        values[match[1]] = match[3]
                self.assertEqual(values["PROJECT"], Path(app).name)
                self.assertEqual(values["SRC_DIR"], "$(VORTEX_HOME)/tests/regression/ai_" + kind)
                expected = base_sources + (["$(AI_DIR)/mlp_host.cpp", "$(AI_DIR)/mlp_runtime.cpp"]
                                           if kind == "mlp" else []) + ["$(OBSERVER_DIR)/observer.cpp"]
                self.assertEqual(shlex.split(values["SRCS"]), expected)
                self.assertEqual(values["VX_SRCS"], "$(VORTEX_HOME)/sw/kernel/ai/matmul.cpp")
                self.assertEqual(values["KERNEL_LIB"], "vortex2")
                self.assertEqual(shlex.split(values["LDFLAGS"]),
                                 ["-Wl,--wrap=vx_device_open", "-Wl,--wrap=vx_device_release"])
                self.assertIn("$(OBSERVER_DIR)/counters.h", shlex.split(values["HDRS"]))
                self.assertIn("$(ROOT_DIR)/sw/VX_config.h", shlex.split(values["HDRS"]))
                self.assertIn("$(ROOT_DIR)/sw/VX_types.h", shlex.split(values["HDRS"]))
                self.assertEqual(text.splitlines().count("include ../common.mk"), 1)
                self.assertFalse((ROOT / app / "main.cpp").exists())
                self.assertFalse((ROOT / app / "kernel.cpp").exists())

    def test_dedicated_profile_apps_do_not_expand_default_regression_inventory(self):
        text = (ROOT / "tests/regression/Makefile").read_text().replace("\\\n", " ")
        tests = re.findall(r"^TESTS\s*:=\s*(.*)$", text, flags=re.MULTILINE)
        self.assertEqual(len(tests), 1)
        names = shlex.split(tests[0])
        self.assertTrue({Path(app).name for app in runner.APPS.values()}.isdisjoint(names))


if __name__ == "__main__":
    unittest.main()
