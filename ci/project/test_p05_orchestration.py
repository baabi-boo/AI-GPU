# SPDX-License-Identifier: Apache-2.0
"""Host-only contracts for independently executed P04 and P05 stages."""

from contextlib import ExitStack, redirect_stderr
import ast
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import p05_execute as runner
from test_p05_ci_workflow import children, command, script, steps, workflow


ROOT = Path(__file__).resolve().parents[2]
HELPER_PROBE = r'''
import importlib, importlib.util, json, pathlib, sys
from unittest import mock
root = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(root / "ci/project"))
importlib.import_module(sys.argv[2])
native = sys.modules["p04_execute"]
audit_path = root / "docs/project/evidence/p04-executor/reviews/audit_provenance.py"
spec = importlib.util.spec_from_file_location("independent_p04_audit", audit_path)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
# Only file-membership logic is under test; this is not a clean-source claim.
with mock.patch.object(native.base, "collect_source", return_value={
        "changed_paths": [], "untracked_paths": []}):
    snapshot = native.source_snapshot(root)
files = audit.inventory(snapshot["files"])
missing, differing = [], []
for helper in native.LOADED_HELPERS:
    audit.identity(helper)
    if helper["path"] not in files:
        missing.append(helper["path"])
    elif helper != files[helper["path"]]:
        differing.append(helper["path"])
print(json.dumps({"scope": "synthetic clean-inventory membership only",
                  "import": sys.argv[2], "helpers": native.LOADED_HELPERS,
                  "snapshot_file_count": len(files), "missing": missing,
                  "differing": differing}, sort_keys=True))
'''


def helper_inventory(module):
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", HELPER_PROBE, str(ROOT), module],
        cwd=ROOT, capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(result.stdout)


def arguments(*options):
    return runner.argument_parser().parse_args([
        "run", "--tools-dir", "/p05-host-only/tools",
        "--work-dir", "/p05-host-only/work", "--output", "/p05-host-only/output",
        "--format", "fp16", *options,
    ])


class SyntheticStageHarness:
    """Inert native inputs and injected processes; no native executable runs."""

    def __init__(self, test):
        temporary = tempfile.TemporaryDirectory(prefix="p05-stage-host-only-")
        test.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.build = self.root / "native-work/simx-fp16"
        self.native = self.root / "native-output"
        self.output = self.root / "python-output"
        for path in (self.build, self.native / "logs", self.root / "tools"):
            path.mkdir(parents=True)
        self.args = arguments(
            "--source-dir", str(ROOT), "--tools-dir", str(self.root / "tools"),
            "--work-dir", str(self.root / "python-work"), "--output", str(self.output),
            "--native-build", str(self.build), "--native-output", str(self.native),
        )
        self.paths = runner.resolve_paths(self.args)
        for name in runner.model_run.artifacts("simx"):
            target = self.build / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("SYNTHETIC HOST-ONLY INERT BUILD FILE\n")
        recipe = self.build / runner.matmul_run.APP / "Makefile"
        recipe.parent.mkdir(parents=True, exist_ok=True)
        recipe.write_bytes((ROOT / runner.matmul_run.APP / "Makefile").read_bytes())
        frozen = runner.hash_artifacts(self.build, runner.model_run.artifacts("simx"))
        cases = runner.select_model_cases(runner.load_model_cases(ROOT), "fp16")
        saved_cases = []
        for case in cases:
            (self.native / "logs" / ("simx-fp16-" + case["id"] + ".log")).write_text(
                "SYNTHETIC HOST-ONLY MODEL OBSERVATION\n")
            saved_cases.append({"id": case["id"], "observations": []})
        report = {"state": "finished", "outcome": "pass", "development": False,
                  "acceptance_claimed": False, "fixture_sha256": "f" * 64,
                  "paths": {name: str(self.paths[name]) if self.paths[name] is not None else None
                            for name in ("source", "tools", "host_bin", "verilator")},
                  "synthetic_host_only_scope": "No compiler, simulator or accelerator was run",
                  "variants": [{"id": "simx-fp16", "qualification_id": "a" * 64,
                                "artifacts_before": frozen, "artifacts_after": frozen,
                                "cases": saved_cases}]}
        (self.native / "report.json").write_text(json.dumps(report))
        (self.native / ".retained-host-only-marker").write_text("SYNTHETIC HOST-ONLY PACKET\n")
        self.original_packet = runner._tree_records(self.native)
        self.events = []
        self.producer_error = ValueError("injected native packet validation rejection")
        self.manifest = {"synthetic_host_only_scope": "not a qualified native manifest"}
        resources = {"available_memory_bytes": runner.BUDGET["max_rss_bytes"],
                     "free_disk_bytes": {name: runner.BUDGET["min_free_bytes"]
                                         for name in ("source", "tools", "work", "output")}}
        source = {"checkout": {"revision": "1" * 40, "tree": "2" * 40,
                               "dirty": False, "changed_paths": [], "untracked_paths": [],
                               "blockers": []}, "files": []}
        tools = {name: {"path": "/synthetic-host-only/" + name}
                 for name in ("make", "g++", "gcc", "ar", "python3")}
        self.original_hash = runner.hash_artifacts
        stack = ExitStack()
        test.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(runner, "source_snapshot", return_value=source))
        stack.enter_context(mock.patch.object(runner.base, "_resources", return_value=resources))
        stack.enter_context(mock.patch.object(runner.base, "tool_inventory", return_value=tools))
        stack.enter_context(mock.patch.object(runner, "hash_artifacts", side_effect=self.hashes))
        stack.enter_context(mock.patch.object(runner, "verify_model", return_value=[]))
        stack.enter_context(mock.patch.object(runner, "run_bounded", side_effect=self.process))
        self.native_execute = stack.enter_context(mock.patch.object(
            runner.model_run, "execute", side_effect=AssertionError("must use preexisting native packet")))
        self.producer = stack.enter_context(mock.patch.object(
            runner.bundle_producer, "create_bundle", side_effect=self.create_bundle))
        stack.enter_context(mock.patch.object(runner.bundle_producer._bundle, "read_manifest",
                                             return_value=(None, None, self.manifest)))
        stack.enter_context(mock.patch.object(runner.bundle_producer._bundle, "validate_files"))

    def hashes(self, root, names):
        if Path(root) == ROOT and tuple(names) == runner.base.DEPENDENCIES:
            return [{"path": name, "sha256": "d" * 64, "size_bytes": 1} for name in names]
        return self.original_hash(root, names)

    def process(self, argv, cwd, env, log, **limits):
        self.events.append(log.stem)
        if log.stem == "package-tools-before":
            raw = b'P05_PACKAGE_TOOLS {"synthetic_host_only":true}\n'
            outcome, code, reason = "pass", 0, None
        elif log.stem == "native-matmul-build":
            raw = b"SYNTHETIC HOST-ONLY STOP BEFORE NATIVE BUILD\n"
            outcome, code, reason = "fail", 9, "injected_stop_before_native_execution"
        else:
            raise AssertionError("unexpected external stage: " + log.stem)
        log.write_bytes(raw)
        return {"outcome": outcome, "exit_code": code, "reason": reason,
                "cleanup_complete": True, "log_sha256": hashlib.sha256(raw).hexdigest(),
                "log_size_bytes": len(raw), "synthetic_host_only_scope": True}

    def create_bundle(self, **kwargs):
        self.events.append("bundle-validation")
        if self.producer_error is not None:
            raise self.producer_error
        kwargs["destination"].mkdir()
        (kwargs["destination"] / "manifest.json").write_text(json.dumps(self.manifest))
        return self.manifest

    def execute(self):
        report = runner.execute(self.args, self.paths)
        self.saved = json.loads((self.output / "report.json").read_text())
        return report


class IndependentNativeStageTests(unittest.TestCase):
    def test_fresh_p04_interpreter_matches_original_auditor_helper_inventory(self):
        observed = helper_inventory("p04_execute")
        self.assertEqual(observed["missing"], [])
        self.assertEqual(observed["differing"], [])
        self.assertIn("ci/project/p04_execute.py", {row["path"] for row in observed["helpers"]})

    def test_importing_p05_does_not_create_a_standalone_p04_inventory(self):
        observed = helper_inventory("p05_execute")
        self.assertIn("ci/project/p05_execute.py", observed["missing"])
        self.assertEqual(observed["differing"], [])

    def test_p05_does_not_invoke_an_imported_p04_execution_entry_point(self):
        tree = ast.parse((ROOT / "ci/project/p05_execute.py").read_text())
        native_aliases = {alias.asname or alias.name for node in ast.walk(tree)
                          if isinstance(node, ast.Import) for alias in node.names
                          if alias.name == "p04_execute"}
        self.assertTrue(native_aliases)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in native_aliases):
                self.assertNotIn(node.func.attr, ("main", "execute"))

    def test_preexisting_native_build_and_packet_are_both_required(self):
        for options in ((), ("--native-build", "/p05-host-only/native/simx-fp16"),
                        ("--native-output", "/p05-host-only/native-packet")):
            with self.subTest(options=options), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    arguments(*options)
                self.assertEqual(raised.exception.code, 2)
        args = arguments("--native-build", "/p05-host-only/native/simx-fp16",
                         "--native-output", "/p05-host-only/native-packet")
        self.assertEqual(args.native_build, Path("/p05-host-only/native/simx-fp16"))
        self.assertEqual(args.native_output, Path("/p05-host-only/native-packet"))

    def test_workflow_runs_original_p04_before_p05_as_separate_steps(self):
        value = workflow(ROOT / ".github/workflows/p05-python.yml")
        job = children(children(value, "jobs", 2), "qualification", 4)
        all_steps = steps(job)
        commands = [(index, command(step), step) for index, step in enumerate(all_steps)
                    if "run" in step]
        native = [item for item in commands if "ci/project/p04_execute.py" in item[1]]
        installed = [item for item in commands if "ci/project/p05_execute.py" in item[1]]
        self.assertEqual(len(native), 1)
        self.assertEqual(len(installed), 1)
        native_index, native_argv, native_step = native[0]
        installed_index, installed_argv, installed_step = installed[0]
        self.assertLess(native_index, installed_index)
        for step in (native_step, installed_step):
            self.assertNotIn("if", step)
            self.assertNotIn("continue-on-error", step)
            self.assertEqual(len(script(step).replace("\\\n", " ").splitlines()), 1)
        self.assertEqual(native_argv[:3], ["python3", "ci/project/p04_execute.py", "run"])
        self.assertEqual(installed_argv[:3], ["python3", "ci/project/p05_execute.py", "run"])
        def option(argv, name):
            self.assertEqual(argv.count(name), 1)
            return argv[argv.index(name) + 1]
        self.assertEqual(option(native_argv, "--backend"), "simx")
        self.assertEqual(option(native_argv, "--iterations"), "2")
        for name in ("--source-dir", "--tools-dir", "--format", "--jobs"):
            self.assertEqual(option(native_argv, name), option(installed_argv, name))
        self.assertEqual(option(installed_argv, "--native-output"), option(native_argv, "--output"))
        self.assertEqual(option(installed_argv, "--native-build"),
                         option(native_argv, "--work-dir") + "/simx-$P05_FORMAT")
        self.assertNotEqual(option(installed_argv, "--work-dir"), option(native_argv, "--work-dir"))
        self.assertNotIn("--development", native_argv)
        self.assertNotIn("--development", installed_argv)


class NativeInputPathTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p05-native-inputs-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for name in ("tools", "native-work/simx-fp16", "native-output"):
            (self.root / name).mkdir(parents=True)
        self.args = arguments(
            "--source-dir", str(ROOT), "--tools-dir", str(self.root / "tools"),
            "--work-dir", str(self.root / "python-work"), "--output", str(self.root / "python-output"),
            "--native-build", str(self.root / "native-work/simx-fp16"),
            "--native-output", str(self.root / "native-output"),
        )

    def test_native_inputs_are_existing_and_new_outputs_remain_fresh(self):
        paths = runner.resolve_paths(self.args)
        self.assertEqual(paths["native_build"], self.root / "native-work/simx-fp16")
        self.assertEqual(paths["native_output"], self.root / "native-output")
        self.assertFalse(paths["work"].exists())
        self.assertFalse(paths["output"].exists())

    def test_missing_or_regular_file_native_input_is_rejected(self):
        regular = self.root / "ordinary-file"
        regular.write_text("host-only path check\n")
        for key in ("native_build", "native_output"):
            original = getattr(self.args, key)
            for path in (self.root / "missing", regular):
                with self.subTest(key=key, path=path):
                    setattr(self.args, key, path)
                    with self.assertRaises((OSError, ValueError)):
                        runner.resolve_paths(self.args)
            setattr(self.args, key, original)

    def test_symlinked_native_input_or_parent_is_rejected(self):
        alias = self.root / "linked-root"
        alias.symlink_to(self.root / "native-work", target_is_directory=True)
        self.args.native_build = alias / "simx-fp16"
        with self.assertRaises((OSError, ValueError)):
            runner.resolve_paths(self.args)
        self.args.native_build = self.root / "native-work/simx-fp16"
        linked = self.root / "linked-packet"
        linked.symlink_to(self.root / "native-output", target_is_directory=True)
        self.args.native_output = linked
        with self.assertRaises((OSError, ValueError)):
            runner.resolve_paths(self.args)

    def test_native_inputs_cannot_overlap_each_other_or_new_outputs(self):
        cases = (("native_output", self.args.native_build),
                 ("native_output", self.root / "native-work"),
                 ("work_dir", self.args.native_output / "new-work"),
                 ("output", self.args.native_build / "new-output"))
        for key, value in cases:
            with self.subTest(key=key, value=value):
                previous = getattr(self.args, key)
                setattr(self.args, key, value)
                with self.assertRaises((OSError, ValueError)):
                    runner.resolve_paths(self.args)
                setattr(self.args, key, previous)

    def test_native_inputs_cannot_be_source_or_tools(self):
        for key in ("native_build", "native_output"):
            previous = getattr(self.args, key)
            for value in (ROOT, ROOT / "ci/project", self.root / "tools"):
                with self.subTest(key=key, value=value):
                    setattr(self.args, key, value)
                    with self.assertRaises((OSError, ValueError)):
                        runner.resolve_paths(self.args)
            setattr(self.args, key, previous)


class NativeValidationBoundaryTests(unittest.TestCase):
    def test_nonobject_native_report_retains_reason_and_stops_before_validation(self):
        for value in ([], None, "invalid report", 1):
            with self.subTest(value=value):
                harness = SyntheticStageHarness(self)
                (harness.native / "report.json").write_text(json.dumps(value))
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertIn("native P04 report must be a JSON object", report["reason"])
                self.assertEqual(report["state"], "finished")
                self.assertEqual(harness.events, ["package-tools-before"])
                harness.producer.assert_not_called()

    def test_native_tool_roots_must_match_the_inputs_monitored_by_p05(self):
        for name in ("tools", "host_bin", "verilator"):
            with self.subTest(name=name):
                harness = SyntheticStageHarness(self)
                path = harness.native / "report.json"
                native = json.loads(path.read_text())
                native["paths"][name] = str(harness.root / ("different-" + name))
                path.write_text(json.dumps(native))
                report = harness.execute()
                self.assertEqual(report["outcome"], "fail")
                self.assertIn("input path differs: " + name, report["reason"])
                self.assertEqual(harness.events, ["package-tools-before"])
                harness.producer.assert_not_called()

    def test_rejected_native_packet_stops_before_any_new_native_build(self):
        harness = SyntheticStageHarness(self)
        report = harness.execute()
        self.assertEqual(report, harness.saved)
        self.assertEqual(report["outcome"], "fail")
        self.assertIn("injected native packet validation rejection", report["reason"])
        self.assertEqual(harness.events, ["package-tools-before", "bundle-validation"])
        harness.native_execute.assert_not_called()
        harness.producer.assert_called_once_with(
            source=ROOT, build=harness.build, native_output=harness.native,
            fmt="fp16", destination=harness.output / "artifacts/bundle",
        )
        receipt = report["bundle_validation"]
        self.assertEqual((receipt["kind"], receipt["function"], receipt["state"]),
                         ("in_process", "p05_bundle.create_bundle", "failed"))
        self.assertNotIn("cleanup_complete", receipt)
        self.assertEqual(runner._tree_records(harness.native), harness.original_packet)
        self.assertEqual(runner._tree_records(harness.output / "native"), harness.original_packet)
        self.assertEqual(report["native_input"]["files"], harness.original_packet)
        self.assertTrue((harness.output / "native/.retained-host-only-marker").is_file())

    def test_completed_validation_precedes_new_native_build_and_is_not_a_command(self):
        harness = SyntheticStageHarness(self)
        harness.producer_error = None
        report = harness.execute()
        self.assertEqual(report["outcome"], "fail")
        self.assertIn("injected_stop_before_native_execution", report["reason"])
        self.assertEqual(harness.events,
                         ["package-tools-before", "bundle-validation", "native-matmul-build"])
        self.assertEqual(report["bundle_validation"]["state"], "passed")
        self.assertEqual([row["id"] for row in report["commands"]],
                         ["package-tools-before", "native-matmul-build"])
        harness.native_execute.assert_not_called()
        self.assertEqual(runner._tree_records(harness.native), harness.original_packet)
        self.assertEqual(runner._tree_records(harness.output / "native"), harness.original_packet)

    def test_interrupted_validation_retains_failure_receipt_and_native_packet(self):
        harness = SyntheticStageHarness(self)
        harness.producer_error = KeyboardInterrupt()
        report = harness.execute()
        self.assertEqual((report["outcome"], report["reason"]), ("fail", "interrupted"))
        self.assertEqual(report["bundle_validation"]["state"], "failed")
        self.assertEqual(harness.events, ["package-tools-before", "bundle-validation"])
        self.assertEqual(runner._tree_records(harness.output / "native"), harness.original_packet)

    def check_packet_drift(self, retained):
        harness = SyntheticStageHarness(self)
        harness.producer_error = None

        def mutate_after_validation(**kwargs):
            manifest = harness.create_bundle(**kwargs)
            target = harness.output / "native" if retained else harness.native
            (target / ".retained-host-only-marker").write_text("injected packet drift\n")
            return manifest

        harness.producer.side_effect = mutate_after_validation
        report = harness.execute()
        self.assertEqual(report["outcome"], "fail")
        self.assertIn(("retained" if retained else "original") + " native P04 packet changed",
                      report["reason"])
        self.assertEqual(harness.events, ["package-tools-before", "bundle-validation"])
        untouched = harness.native if retained else harness.output / "native"
        self.assertEqual(runner._tree_records(untouched), harness.original_packet)

    def test_original_packet_drift_stops_before_new_native_build(self):
        self.check_packet_drift(retained=False)

    def test_retained_packet_drift_stops_before_new_native_build(self):
        self.check_packet_drift(retained=True)


if __name__ == "__main__":
    unittest.main()
