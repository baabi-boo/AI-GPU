# SPDX-License-Identifier: Apache-2.0
"""Host checks for historical baseline replay CI, never native qualification.

Only the current workflow's small identity/interpreter blocks and a synthetic
process stand-in execute. Original archives and their workflow remain data.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

import p04_model_contract
import p06_contract
import p06_replay
from test_p05_ci_workflow import children, path_filters, scalars, script, steps, workflow
from test_p06_ci_contract import covers


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/p06-baseline.yml"
REVISION = "84b6ca0ca75fba248ba330642bbf8764db3d459c"
ARCHIVES = {
    "fp16": "aaf54ff60b8f4f889264fb3efa4249cbdb02a7fad2b20124b4ad0ba9ae2f41dc",
    "bf16": "f19f174879e2c1fb120a3328ec919d42b4d67f59ba056ceb6e0b6f5607f4996b",
}


def analysis_inputs():
    names = set(p06_contract.ANALYSIS_SOURCE_PATHS + p04_model_contract.ARTIFACT_PATHS)
    names.update(row["path"] for row in p06_replay.TRUSTED_SOURCES)
    names.update({
        ".github/workflows/p06-baseline.yml", "ci/project/p06_analyze.py",
        p06_contract.MANIFEST_PATH, p06_replay.ARCHIVE_READER_PATH,
        "ci/project/fixtures/p02_tfr_v1.json",
        "ci/project/p04_model_manifest.json",
        "docs/project/evidence/p06-baseline/archive-index.json",
        Path(__file__).relative_to(ROOT).as_posix(),
    })
    names.update("docs/project/evidence/p06-baseline/archives/simx-" + fmt + ".zip"
                 for fmt in ARCHIVES)
    return names


class FrozenBaselineReplayWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = workflow(WORKFLOW)
        cls.events = children(cls.workflow, "on", 2)
        cls.jobs = children(cls.workflow, "jobs", 2)
        cls.job = children(cls.jobs, "replay", 4)
        cls.steps = steps(cls.job)

    def one(self, key, value):
        found = [step for step in self.steps if step.get(key, (None,))[0] == value]
        self.assertEqual(len(found), 1, (key, value))
        return found[0]

    def python_body(self, step_name, invocation):
        lines = script(self.one("name", step_name)).splitlines()
        self.assertEqual(lines[0], invocation + " <<'PYTHON'")
        self.assertEqual(lines[-1], "PYTHON")
        return "\n".join(lines[1:-1])

    def identity_environment(self, root):
        return {
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
            "RUNNER_TEMP": str(root), "GITHUB_ENV": str(root / "github-env"),
            "GITHUB_SHA": "1" * 40, "GITHUB_EVENT_NAME": "push", "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "2", "GITHUB_JOB": "replay",
            "GITHUB_REPOSITORY": "host-only/synthetic", "GITHUB_REF": "refs/heads/master",
        }

    def test_master_pull_request_and_manual_events_keep_read_only_boundary(self):
        self.assertEqual(set(self.workflow), {"name", "on", "permissions", "concurrency", "jobs"})
        self.assertEqual(self.workflow["name"], ("P06 Frozen Baseline Replay", []))
        self.assertEqual(set(self.events), {"push", "pull_request", "workflow_dispatch"})
        self.assertEqual(self.events["workflow_dispatch"], ("", []))
        push = children(self.events, "push", 4)
        self.assertEqual(set(push), {"branches", "paths"})
        self.assertEqual(push["branches"], ("[master]", []))
        self.assertEqual(set(children(self.events, "pull_request", 4)), {"paths"})
        self.assertEqual(scalars(children(self.workflow, "permissions", 2)), {"contents": "read"})
        self.assertEqual(scalars(children(self.workflow, "concurrency", 2)), {
            "group": "p06-baseline-${{ github.event_name }}-${{ github.ref }}",
            "cancel-in-progress": "false",
        })
        self.assertNotRegex(WORKFLOW.read_text(),
                            r"secrets\s*\.|pull_request_target|self-hosted|write-all|id-token:")

    def test_every_current_reader_oracle_and_original_archive_input_triggers(self):
        self.assertEqual(path_filters(self.events, "push"), path_filters(self.events, "pull_request"))
        for event in ("push", "pull_request"):
            patterns = path_filters(self.events, event)
            for path in sorted(analysis_inputs()):
                with self.subTest(event=event, path=path):
                    self.assertTrue(covers(patterns, path), "uncovered replay input: " + path)
            # This transitive model-contract input previously had no route.
            self.assertIn("LICENSE", p04_model_contract.ARTIFACT_PATHS)
            self.assertFalse(covers(patterns - {"LICENSE"}, "LICENSE"))
            self.assertFalse(covers(patterns - {"docs/project/evidence/p05-torch/reviews/archive_reader.py"},
                                    p06_replay.ARCHIVE_READER_PATH))

    def test_job_is_bounded_replay_with_no_native_matrix_or_installation(self):
        self.assertEqual(set(self.jobs), {"replay"})
        self.assertEqual(set(self.job), {"name", "runs-on", "timeout-minutes", "defaults", "env", "steps"})
        self.assertEqual(self.job["name"], ("Verify accepted cold baseline as retained data", []))
        self.assertEqual(self.job["runs-on"], ("ubuntu-22.04", []))
        self.assertEqual(self.job["timeout-minutes"], ("15", []))
        self.assertEqual(scalars(children(self.job, "env", 6)), {"PYTHONDONTWRITEBYTECODE": "'1'"})
        defaults = children(self.job, "defaults", 6)
        self.assertEqual(set(defaults), {"run"})
        self.assertEqual(scalars(children(defaults, "run", 8)), {"shell": "bash"})
        for step in self.steps:
            if "run" in step:
                self.assertNotRegex(script(step),
                                    r"p06_execute|p04_ci_prepare|toolchain_install|install_dependencies|"
                                    r"(?:curl|wget|make|sudo|git clone)\s")

    def test_checkout_actions_and_unconditional_steps_cannot_hide_replay_failure(self):
        self.assertEqual([step["uses"][0] for step in self.steps if "uses" in step], [
            "actions/checkout@v4", "actions/setup-python@v5", "actions/upload-artifact@v4",
        ])
        checkout = self.one("uses", "actions/checkout@v4")
        self.assertEqual(set(checkout), {"uses", "with"})
        self.assertEqual(scalars(children(checkout, "with", 10)), {
            "fetch-depth": "1", "persist-credentials": "false",
        })
        for step in self.steps:
            self.assertTrue(set(step) <= {"name", "uses", "with", "run", "if"})
            self.assertNotIn("continue-on-error", step)
            if "if" in step:
                self.assertIs(step, self.one("uses", "actions/upload-artifact@v4"))
                self.assertEqual(step["if"], ("always()", []))

    def test_replay_command_pins_both_original_archives_and_original_revision(self):
        step = self.one("name", "Replay both original digest-pinned archives")
        self.assertEqual(set(step), {"name", "run"})
        lines = script(step).replace("\\\n", " ").splitlines()
        self.assertEqual(lines[0], "set -euo pipefail")
        self.assertEqual(len(lines), 2)
        expected = ["python3", "ci/project/p06_analyze.py"]
        for fmt, digest in ARCHIVES.items():
            expected.extend(["--" + fmt + "-archive",
                             "$PWD/docs/project/evidence/p06-baseline/archives/simx-" + fmt + ".zip",
                             "--" + fmt + "-sha256", digest])
        expected.extend(["--source-revision", REVISION,
                         "--output", "$P06_REPLAY_ROOT/evidence/analysis.json",
                         "2>&1", "|", "tee", "$P06_REPLAY_ROOT/evidence/replay.log"])
        self.assertEqual(shlex.split(lines[1]), expected)
        index = json.loads((ROOT / "docs/project/evidence/p06-baseline/archive-index.json").read_text())
        self.assertEqual(index["source_revision"], REVISION)
        self.assertEqual({row["format"]: row["sha256"] for row in index["archives"]}, ARCHIVES)
        self.assertNotIn("$GITHUB_SHA", lines[1])
        self.assertNotRegex(script(step), r"\|\|\s*true|set\s+\+|;|(?:^|\s)exit\s+0")

    def test_python_pin_identity_verification_and_order_precede_replay(self):
        setup = self.one("uses", "actions/setup-python@v5")
        self.assertEqual(scalars(children(setup, "with", 10)), {
            "python-version": "'3.12.14'", "architecture": "x64", "check-latest": "false",
        })
        probe = self.one("name", "Retain and verify Python interpreter identity")
        body = self.python_body("Retain and verify Python interpreter identity", "python3 -I -")
        for token in ("'python-provision.json'", "data['python_version'] != [3, 12, 14]",
                      "data['implementation'] != 'CPython'", "data['platform'] != 'linux'",
                      "Path(data['python3_on_path']).resolve() != Path(sys.executable).resolve()",
                      "raise SystemExit("):
            self.assertIn(token, body)
        order = [self.one("uses", "actions/checkout@v4"),
                 self.one("name", "Initialize retained replay identity"), setup, probe,
                 self.one("name", "Replay both original digest-pinned archives"),
                 self.one("uses", "actions/upload-artifact@v4")]
        self.assertEqual(self.steps, order)

    def test_current_identity_block_retains_candidate_and_historical_identities(self):
        body = self.python_body("Initialize retained replay identity", "python3 -")
        with tempfile.TemporaryDirectory(prefix="p06-replay-ci-identity-") as temporary:
            root = Path(temporary)
            env = self.identity_environment(root)
            result = subprocess.run([sys.executable, "-I", "-"], input=body,
                                    cwd=ROOT, env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = root / "p06-baseline-replay/evidence"
            data = json.loads((evidence / "job.json").read_text())
            self.assertEqual(data, {**{key: value for key, value in env.items()
                                      if key.startswith("GITHUB_") and key != "GITHUB_ENV"},
                                   "scope": "p06-frozen-baseline-replay", "native_execution": "not_run",
                                   "baseline_source_revision": REVISION, "acceptance_claimed": False,
                                   "workflow_sha256": hashlib.sha256(WORKFLOW.read_bytes()).hexdigest()})
            self.assertNotEqual(data["GITHUB_SHA"], data["baseline_source_revision"])
            self.assertEqual((evidence / "workflow.yml").read_bytes(), WORKFLOW.read_bytes())
            self.assertEqual((root / "github-env").read_text(),
                             "P06_REPLAY_ROOT=" + str(root / "p06-baseline-replay") + "\n")
            # A repeated attempt cannot overwrite prior identity evidence.
            before = {path.name: path.read_bytes() for path in evidence.iterdir()}
            repeated = subprocess.run([sys.executable, "-I", "-"], input=body,
                                      cwd=ROOT, env=env, text=True, capture_output=True, timeout=10)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertEqual({path.name: path.read_bytes() for path in evidence.iterdir()}, before)

    def test_current_interpreter_probe_records_identity_and_rejects_path_mismatch(self):
        body = self.python_body("Retain and verify Python interpreter identity", "python3 -I -")
        with tempfile.TemporaryDirectory(prefix="p06-replay-ci-python-") as temporary:
            root = Path(temporary)
            (root / "evidence").mkdir()
            (root / "wrong-bin").mkdir()
            wrong = root / "wrong-bin/python3"
            wrong.write_text("This file is not executed by the test.\n")
            wrong.chmod(0o700)
            for label, search in (
                    ("actual", str(Path(sys.executable).parent) + os.pathsep + os.defpath),
                    ("path-mismatch", str(root / "wrong-bin"))):
                with self.subTest(identity=label):
                    env = {"PATH": search, "P06_REPLAY_ROOT": str(root)}
                    result = subprocess.run([sys.executable, "-I", "-"], input=body,
                                            cwd=ROOT, env=env, text=True, capture_output=True, timeout=10)
                    data = json.loads((root / "evidence/python-provision.json").read_text())
                    self.assertEqual(data["python_version"], list(sys.version_info[:3]))
                    self.assertEqual(data["executable"], sys.executable)
                    self.assertEqual(data["python3_on_path"], shutil.which("python3", path=search))
                    correct = (data["python_version"] == [3, 12, 14]
                               and data["implementation"] == "CPython" and data["platform"] == "linux"
                               and Path(data["python3_on_path"]).resolve() == Path(sys.executable).resolve())
                    if label == "path-mismatch":
                        self.assertFalse(correct)
                        self.assertEqual(data["python3_on_path"], str(wrong))
                    self.assertEqual(result.returncode, 0 if correct else 1, result.stderr)
                    if not correct:
                        self.assertIn("Python interpreter identity differs", result.stderr)

    def test_real_replay_shell_propagates_process_failure_and_retains_console(self):
        body = script(self.one("name", "Replay both original digest-pinned archives"))
        with tempfile.TemporaryDirectory(prefix="p06-replay-ci-pipeline-") as temporary:
            root = Path(temporary)
            (root / "evidence").mkdir()
            (root / "bin").mkdir()
            standin = root / "bin/python3"
            for code in (0, 7):
                with self.subTest(exit_code=code):
                    standin.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$P06_REPLAY_ROOT/evidence/argv.txt\"\n"
                                       "printf '%s\\n' 'synthetic replay process'\nexit " + str(code) + "\n")
                    standin.chmod(0o700)
                    env = {"PATH": str(root / "bin") + os.pathsep + os.defpath,
                           "P06_REPLAY_ROOT": str(root)}
                    result = subprocess.run(["bash", "-e", "-c", body], cwd=ROOT, env=env,
                                            text=True, capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, code, result.stderr)
                    self.assertEqual(result.stdout, "synthetic replay process\n")
                    self.assertEqual((root / "evidence/replay.log").read_text(), result.stdout)
                    argv = (root / "evidence/argv.txt").read_text().splitlines()
                    for fmt in ARCHIVES:
                        actual = argv[argv.index("--" + fmt + "-archive") + 1]
                        expected = ROOT / ("docs/project/evidence/p06-baseline/archives/simx-" + fmt + ".zip")
                        self.assertTrue(Path(actual).is_absolute())
                        self.assertEqual(actual, str(expected))
                        self.assertEqual(Path(actual).resolve(), expected)
                        self.assertTrue(Path(actual).is_file())

    def test_failure_packet_upload_is_complete_and_uniquely_named(self):
        upload = self.one("uses", "actions/upload-artifact@v4")
        self.assertEqual(set(upload), {"name", "if", "uses", "with"})
        self.assertEqual(upload["if"], ("always()", []))
        self.assertEqual(scalars(children(upload, "with", 10)), {
            "name": "p06-baseline-replay-${{ github.sha }}-run${{ github.run_id }}-attempt${{ github.run_attempt }}",
            "path": "${{ runner.temp }}/p06-baseline-replay/evidence", "if-no-files-found": "error",
            "retention-days": "30", "compression-level": "6", "include-hidden-files": "true",
        })
        self.assertEqual(self.steps[-1], upload)

    def test_every_current_shell_block_is_syntactically_valid(self):
        for step in self.steps:
            if "run" in step:
                with self.subTest(step=step.get("name")):
                    result = subprocess.run(["bash", "-n"], input=script(step), text=True,
                                            capture_output=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
