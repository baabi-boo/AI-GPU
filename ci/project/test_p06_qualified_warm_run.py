# SPDX-License-Identifier: Apache-2.0
"""Controlled orchestration receipts, never GPU execution or qualification evidence."""

from copy import deepcopy
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import p06_qualified_warm_run as runner


def digest(body):
    return hashlib.sha256(body).hexdigest()


class QualifiedWarmRunTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-qualified-warm-run-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source, self.archives, self.repositories, self.host = [self.root / name
            for name in ("source", "archives", "repositories", "host-bin")]
        for path in (self.source, self.archives, self.repositories, self.host):
            path.mkdir()
        for name in runner.SOURCE_FILES:
            target = self.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(runner.ROOT / name, target)
        self.workspace = self.root / "attempt"
        self.revision = "a" * 40
        self.checkout = {"revision": self.revision, "dirty": False, "blockers": []}
        self.interpreter = dict(runner.interpreter_identity(), python_version=[3, 12, 14],
                                implementation="CPython", platform="linux")
        self.originals = {}
        self.original_pins = {}
        for name in runner.ORIGINAL_ARCHIVES:
            path = self.root / (name + ".zip")
            body = ("synthetic " + name + "; no archived native evidence\n").encode()
            path.write_bytes(body)
            self.originals[name] = path
            self.original_pins[name] = {"sha256": digest(body), "size_bytes": len(body)}
        self.args = SimpleNamespace(source_dir=self.source, workspace_dir=self.workspace,
            expected_revision=self.revision, archive_root=self.archives,
            dependency_repositories=self.repositories, host_bin=self.host, **self.originals)
        self.paths = {"source": str(self.source), "workspace": str(self.workspace), "archive": str(self.archives),
            "repositories": str(self.repositories), "host_bin": str(self.host),
            **{key: str(value) for key, value in self.originals.items()}}
        self.observed = []
        self.change = None
        for patch in (
            mock.patch.object(runner, "ROOT", self.source),
            mock.patch.object(runner, "collect_source", side_effect=lambda root: deepcopy(self.checkout)),
            mock.patch.object(runner, "interpreter_identity", side_effect=lambda: deepcopy(self.interpreter)),
            mock.patch.object(runner, "ORIGINAL_ARCHIVES", self.original_pins),
            mock.patch.object(runner.shutil, "disk_usage", return_value=SimpleNamespace(free=50 * 2**30)),
            mock.patch.object(runner, "available_memory_bytes", return_value=8 * 2**30),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def warm_document(self, document):
        evidence = self.workspace / "evidence"
        plan = runner.qualification.process_plan(self.source)
        pin = digest((evidence / "dependency-build/report.json").read_bytes())
        document.update(scope=runner.qualification.SCOPE, native_execution="run",
            dependency_receipt_sha256=pin, counter_qualification_sha256=runner.qualification.SOURCE_PROOF_SHA256,
            native_preflight_passed=True, native_lifetime_passed=True,
            dependency_source_to_loaded_binary_verified=True, counter_qualification_passed=True,
            qualified_warm_passed=True, expected_counts=dict(runner.COMPLETE_COUNTS),
            completed_counts=dict(runner.COMPLETE_COUNTS), expected_processes=plan,
            # This deliberately unfavorable synthetic value is not interpreted by orchestration.
            hypothesis="not_satisfied", processes=[], commands=[])
        for planned in plan:
            document["processes"].append(dict(planned, outcome="pass", observation={
                "warm": {"operations": [{"checked": 32, "dispatch": {"launches": 1}} for _ in range(33)],
                    "summary": {"snapshots": {str(index): {"counters":
                        [{"enabled": True} for _ in range(33)] + [{"enabled": False} for _ in range(12)]}
                        for index in range(4)}}},
                "witness": {"snapshots": [{} for _ in range(4)], "reads": [{} for _ in range(264)],
                    "cache_flush_reads": [{} for _ in range(33)], "observation": {"dcr_read_completed": 297}}}))
        for name, native in [*(('build-' + str(index), False) for index in range(33)),
                             *((row["id"], True) for row in plan)]:
            document["commands"].append({"id": name, "native_process": native, "outcome": "pass",
                "process_started": True, "exit_code": 0, "reason": None, "cleanup_complete": True})
        for field in ("source_before", "source_after"):
            relative = "snapshots/" + field.replace("_", "-") + ".json"
            path = evidence / "qualified-warm" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            body = json.dumps({"checkout": self.checkout}, sort_keys=True).encode() + b"\n"
            path.write_bytes(body)
            document[field] = {"path": relative, "sha256": digest(body), "size_bytes": len(body)}

    def child(self, argv, cwd, environment, log, **limits):
        name = log.stem
        self.observed.append({"id": name, "argv": argv, "cwd": cwd, "environment": environment, "limits": limits})
        contracts = {"preparation": "p06-local-dependency-preparation-v1",
            "dependency-build": runner.dependency.CONTRACT_ID, "qualified-warm": runner.qualification.CONTRACT_ID}
        document = {"schema_version": 1, "contract_id": contracts[name], "expected_revision": self.revision,
            "state": "finished", "outcome": "pass", "reason": None, "failures": [],
            **dict.fromkeys(runner.qualification.FALSE_CLAIMS, False)}
        if name == "preparation":
            document.update(execution_origin="local", native_execution="not_run")
        elif name == "dependency-build":
            document["fresh_dependency_build_passed"] = True
        else:
            self.warm_document(document)
        return_code = self.change(name, document, argv) if self.change else 0
        relative = "dependency-preparation.json" if name == "preparation" else name + "/report.json"
        path = self.workspace / "evidence" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document) + "\n")
        body = ("controlled child; no native evidence\n"
                + json.dumps(runner.report_terminal(name, document, self.paths)) + "\n").encode()
        log.write_bytes(body)
        return {"process_started": True, "outcome": "pass" if return_code == 0 else "fail",
            "exit_code": return_code, "reason": None if return_code == 0 else "nonzero_exit",
            "duration_seconds": 0.001, "log_sha256": digest(body), "log_size_bytes": len(body),
            "peak_rss_bytes": 1024, "cleanup_complete": True,
            "limitations": list(runner.PROCESS_LIMITATIONS)}

    def run_route(self, child=None):
        with mock.patch.object(runner, "run_bounded", side_effect=child or self.child):
            result = runner.execute(self.args)
        retained = json.loads((self.workspace / "evidence" / runner.RECEIPT_PATH).read_text())
        self.assertEqual(result, retained)
        self.assertEqual(result["state"], "finished")
        self.assertTrue(all(result[field] is False for field in runner.qualification.FALSE_CLAIMS))
        return result

    def test_three_stages_bind_originals_counts_logs_sources_and_fixed_budgets(self):
        with mock.patch.dict(os.environ, {"LD_LIBRARY_PATH": "/untrusted", "MAKEFLAGS": "-j999",
                                         "UNRELATED_SECRET": "unrelated-parent-value"}):
            result = self.run_route()
        self.assertEqual(result["outcome"], "pass", result["reason"])
        self.assertTrue(result["orchestration_passed"])
        self.assertEqual(result["scope"], runner.SCOPE)
        self.assertEqual(result["completed_counts"], runner.COMPLETE_COUNTS)
        self.assertEqual([row["id"] for row in result["stages"]], list(runner.STAGE_NAMES))
        self.assertEqual(set(result["reports"]), {*runner.STAGE_NAMES, "native-source-before", "native-source-after"})
        self.assertTrue(result["source_stable"])
        self.assertTrue(result["inputs_stable"])
        self.assertTrue(result["selected_sources_stable"])
        self.assertEqual(result["interpreter"], result["interpreter_after"])
        for row in self.observed:
            self.assertEqual(row["argv"][:2], [sys.executable, "-B"])
            self.assertEqual(row["cwd"], self.source)
            self.assertEqual(row["limits"]["max_rss_bytes"], 4 * 2**30)
            self.assertEqual(row["limits"]["max_log_bytes"], 16 * 2**20)
            self.assertEqual(row["limits"]["min_free_bytes"], 15 * 2**30)
            self.assertLessEqual(row["limits"]["timeout_seconds"], 5400)
            self.assertEqual(row["environment"]["THREADS"], "1")
            self.assertEqual(row["environment"]["MAKEFLAGS"], "-j2")
            self.assertNotIn("UNRELATED_SECRET", row["environment"])
            self.assertNotIn("LD_LIBRARY_PATH", row["environment"])
        native = self.observed[-1]["argv"]
        for flag, value in (("--jobs", "2"), ("--timeout-seconds", "1800"), ("--run-timeout-seconds", "180"),
                ("--dependency-receipt-sha256", result["dependency_receipt_sha256"]),
                ("--counter-qualification-sha256", runner.qualification.SOURCE_PROOF_SHA256)):
            self.assertEqual(native[native.index(flag) + 1], value)
        for name, descriptor in result["reports"].items():
            self.assertEqual(digest((self.workspace / "evidence" / descriptor["path"]).read_bytes()), descriptor["sha256"], name)
        self.assertTrue(result["stages"][-1]["report_summary"]["qualified_warm_passed"])
        self.assertNotIn("hypothesis", result)

    def test_raw_large_warm_report_uses_the_complete_population_decoder(self):
        def change(name, document, argv):
            if name == "qualified-warm":
                document["opaque_retained_detail"] = "x" * (17 * 1024**2)
            return 0
        self.change = change
        with mock.patch.object(runner.qualified_warm_replay, "decode_report",
                               wraps=runner.qualified_warm_replay.decode_report) as decode:
            result = self.run_route()
        self.assertEqual(result["outcome"], "pass", result["reason"])
        self.assertEqual(decode.call_count, 1)
        self.assertGreater(result["reports"]["qualified-warm"]["size_bytes"], 16 * 1024**2)
        self.assertEqual(result["qualified_warm_report_sha256"], result["reports"]["qualified-warm"]["sha256"])

    def test_failed_dependency_preserves_original_receipts_and_final_source_observation(self):
        def change(name, document, argv):
            if name == "dependency-build":
                document.update(outcome="fail", reason="deliberate compile failure", failures=["compile"])
                return 9
            return 0
        self.change = change
        result = self.run_route()
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(len(self.observed), 2)
        self.assertEqual(result["stages"][-1]["exit_code"], 9)
        self.assertEqual(result["stages"][-1]["report_summary"]["reason"], "deliberate compile failure")
        self.assertIn("dependency-build", result["reports"])
        self.assertEqual(result["source_before"], result["source_after"])
        self.assertEqual(result["inputs_before"], result["inputs_after"])
        self.assertFalse((self.workspace / "evidence/qualified-warm").exists())
        self.assertEqual(result["native_execution"], "not_run")

    def test_monitor_exception_keeps_partial_unparseable_report_log_and_unknown_execution(self):
        partial = b'{"state":"running","commands":['
        def child(argv, cwd, environment, log, **limits):
            if log.stem != "qualified-warm":
                return self.child(argv, cwd, environment, log, **limits)
            path = self.workspace / "evidence/qualified-warm/report.json"
            path.parent.mkdir()
            path.write_bytes(partial)
            log.write_bytes(b"native child observation was interrupted\n")
            raise OSError("monitor contact lost")
        result = self.run_route(child)
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["native_execution"], "unknown")
        self.assertIn("monitor contact lost", result["reason"])
        self.assertEqual(result["reports"]["qualified-warm"]["sha256"], digest(partial))
        self.assertIn("raw_log", result["stages"][-1])
        self.assertTrue(result["stages"][-1]["retention_errors"])
        self.assertIsNone(result["qualified_warm_report_sha256"])
        self.assertIsNotNone(result["source_after"])
        self.assertFalse((self.workspace / "evidence/qualified-warm/snapshots").exists())

    def test_consistent_log_hash_cannot_hide_terminal_disagreement(self):
        def child(*args, **kwargs):
            result = self.child(*args, **kwargs)
            body = b'{"outcome":"pass","reason":null}\n'
            args[3].write_bytes(body)
            result.update(log_sha256=digest(body), log_size_bytes=len(body))
            return result
        result = self.run_route(child)
        self.assertIn("terminal output differs", result["reason"])
        self.assertEqual(len(self.observed), 1)

    def test_wrong_population_and_performance_acceptance_are_rejected(self):
        base_workspace = self.workspace
        changes = {
            "float-count": lambda doc: doc["completed_counts"].update(launches=792.0),
            "short-population": lambda doc: doc["processes"].pop(),
            "reordered": lambda doc: doc["processes"].reverse(),
            "missing-operation": lambda doc: doc["processes"][0]["observation"]["warm"]["operations"].pop(),
            "bad-observation": lambda doc: doc["processes"][0]["observation"]["witness"]["reads"].pop(),
            "string-witness-population": lambda doc: doc["processes"][0]["observation"]["witness"].update(reads="x" * 264),
            "string-witness-records": lambda doc: doc["processes"][0]["observation"]["witness"].update(reads=["x"] * 264),
            "list-counter-snapshots": lambda doc: doc["processes"][0]["observation"]["warm"]["summary"].update(snapshots=[]),
            "missing-command": lambda doc: doc["commands"].pop(),
            "native-command-order": lambda doc: doc["commands"].reverse(),
            "acceptance": lambda doc: doc.update(performance_acceptance=True),
        }
        for name, mutate in changes.items():
            with self.subTest(boundary=name):
                self.workspace = base_workspace.with_name(name)
                self.args.workspace_dir = self.workspace
                self.paths["workspace"] = str(self.workspace)
                self.change = lambda stage, doc, argv: (mutate(doc) if stage == "qualified-warm" else None) and 0 or 0
                result = self.run_route()
                self.assertEqual(result["outcome"], "fail")
                self.assertFalse(result["orchestration_passed"])
                self.assertEqual(result["native_execution"], "run")
                self.assertIn("qualified-warm", result["reports"])

    def test_earlier_report_and_log_mutation_are_detected_at_closeout(self):
        def change(name, document, argv):
            if name == "qualified-warm":
                for relative in ("dependency-preparation.json", runner.LOG_ROOT + "/preparation.log"):
                    path = self.workspace / "evidence" / relative
                    path.write_bytes(path.read_bytes() + b" ")
            return 0
        self.change = change
        result = self.run_route()
        self.assertEqual(result["outcome"], "fail")
        reasons = " ".join(row["reason"] for row in result["failures"])
        self.assertIn("report changed after its stage", reasons)
        self.assertIn("log changed after its stage", reasons)
        self.assertFalse(result["orchestration_passed"])

    def test_source_helper_and_original_changes_are_retained_after_native_failure(self):
        def change(name, document, argv):
            if name == "qualified-warm":
                self.checkout["revision"] = "b" * 40
                helper = self.source / "ci/project/baseline_process.py"
                helper.write_bytes(helper.read_bytes() + b"\n")
                self.originals["control_archive"].write_bytes(b"changed original retained untouched by wrapper")
                return 7
            return 0
        self.change = change
        result = self.run_route()
        self.assertFalse(result["source_stable"])
        self.assertFalse(result["selected_sources_stable"])
        self.assertFalse(result["inputs_stable"])
        self.assertEqual(result["source_after"]["revision"], "b" * 40)
        self.assertNotEqual(result["inputs_before"]["control_archive"], result["inputs_after"]["control_archive"])
        self.assertEqual(result["outcome"], "fail")

    def test_changed_helper_stops_before_the_next_child(self):
        def change(name, document, argv):
            helper = self.source / "ci/project/baseline_process.py"
            helper.write_bytes(helper.read_bytes() + b"\n")
            return 0
        self.change = change
        result = self.run_route()
        self.assertIn("helper source changed", result["reason"])
        self.assertEqual(len(self.observed), 1)

    def test_shared_deadline_does_not_start_another_stage(self):
        clock = [0.0]
        self.change = lambda name, document, argv: clock.__setitem__(0, 5401.0) or 0
        with mock.patch.object(runner.time, "monotonic", side_effect=lambda: clock[0]):
            result = self.run_route()
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("90-minute", result["reason"])
        self.assertEqual(len(self.observed), 1)
        self.assertEqual(result["duration_seconds"], 5401.0)
        self.assertIsNotNone(result["source_after"])

    def test_incomplete_cleanup_and_never_started_native_child_do_not_pass(self):
        def child(argv, cwd, environment, log, **limits):
            if log.stem == "qualified-warm":
                return {"process_started": False, "outcome": "blocked", "exit_code": None,
                        "reason": "disk_reserve", "cleanup_complete": True}
            return self.child(argv, cwd, environment, log, **limits)
        result = self.run_route(child)
        self.assertEqual(result["native_execution"], "not_run")
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("disk_reserve", result["reason"])
        self.assertNotIn("qualified-warm", result["reports"])
        self.workspace = self.root / "incomplete-cleanup"
        self.args.workspace_dir = self.workspace
        self.paths["workspace"] = str(self.workspace)
        def incomplete(*args, **kwargs):
            return dict(self.child(*args, **kwargs), cleanup_complete=False)
        result = self.run_route(incomplete)
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(len(result["stages"]), 1)
        self.assertFalse(result["stages"][0]["cleanup_complete"])

    def test_report_hardlink_is_rejected_without_deleting_the_original(self):
        def child(*args, **kwargs):
            result = self.child(*args, **kwargs)
            path = self.workspace / "evidence/dependency-preparation.json"
            os.link(path, self.workspace / "alias.json")
            return result
        result = self.run_route(child)
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("single-link regular", result["reason"])
        self.assertTrue((self.workspace / "alias.json").exists())
        self.assertEqual(len(result["stages"]), 1)

    def test_native_source_snapshot_traversal_is_rejected(self):
        def change(name, document, argv):
            if name == "qualified-warm":
                document["source_before"]["path"] = "../dependency-build/report.json"
            return 0
        self.change = change
        result = self.run_route()
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("safe relative literal", result["reason"])

    def test_dirty_source_and_resource_shortfall_remain_preexecution_blocks(self):
        self.checkout["dirty"] = True
        result = self.run_route()
        self.assertEqual(result["outcome"], "blocked")
        self.assertEqual(self.observed, [])
        self.assertIsNotNone(result["source_after"])
        self.checkout["dirty"] = False
        self.workspace = self.root / "insufficient-resources"
        self.args.workspace_dir = self.workspace
        self.paths["workspace"] = str(self.workspace)
        with mock.patch.object(runner, "available_memory_bytes", return_value=4 * 2**30 - 1):
            result = self.run_route()
        self.assertEqual(result["outcome"], "blocked")
        self.assertIn("15 GiB disk reserve and 4 GiB", result["reason"])
        self.assertEqual(self.observed, [])
        self.assertTrue(result["inputs_stable"])

    def test_wrong_frozen_original_retains_its_identity_without_launch(self):
        self.originals["diagnostic_archive"].write_bytes(b"wrong archived input")
        result = self.run_route()
        self.assertEqual(result["outcome"], "blocked")
        self.assertIn("frozen original", result["reason"])
        self.assertIn("diagnostic_archive", result["inputs_before"])
        self.assertEqual(self.observed, [])

    def test_existing_workspace_cannot_be_overwritten_or_resumed(self):
        self.run_route()
        path = self.workspace / "evidence" / runner.RECEIPT_PATH
        original = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "implicit resume"):
            runner.execute(self.args)
        self.assertEqual(path.read_bytes(), original)

    def test_real_failed_child_retains_raw_output_without_native_execution(self):
        path = self.source / "ci/project/p06_dependency_local_prepare.py"
        path.write_text('print("controlled child failure")\nraise SystemExit(7)\n')
        result = runner.execute(self.args)
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["stages"][0]["exit_code"], 7)
        self.assertTrue(result["stages"][0]["cleanup_complete"])
        self.assertEqual(result["native_execution"], "not_run")
        self.assertEqual((self.workspace / "evidence" / runner.LOG_ROOT / "preparation.log").read_text(),
                         "controlled child failure\n")
        self.assertEqual(len(result["stages"]), 1)
        self.assertIsNotNone(result["source_after"])

    def test_selected_source_count_and_byte_bounds_fail_closed(self):
        with mock.patch.object(runner, "MAX_SOURCE_FILES", len(runner.SOURCE_FILES) - 1):
            with self.assertRaisesRegex(ValueError, "file bound"):
                runner.selected_sources(self.source)
        with mock.patch.object(runner, "MAX_SOURCE_TOTAL_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "total byte bound"):
                runner.selected_sources(self.source)
        self.assertFalse(any(Path(name).name.startswith("test_") for name in runner.SOURCE_FILES))
        self.assertIn(runner.SOURCE_FILE, runner.SOURCE_FILES)
        self.assertIn("ci/project/baseline_process.py", runner.SOURCE_FILES)
        self.assertIn("ci/project/p06_qualified_warm_inputs.py", runner.SOURCE_FILES)

    def test_stage_argv_is_accepted_by_each_real_parser_without_execution(self):
        root = Path(__file__).resolve().parents[2]
        program = """
import argparse, importlib, json, sys
module = importlib.import_module(sys.argv[1])
original = argparse.ArgumentParser.parse_args
class Parsed(BaseException):
    pass
def parse(parser, args=None, namespace=None):
    original(parser, args, namespace)
    raise Parsed
argparse.ArgumentParser.parse_args = parse
try:
    module.main(json.loads(sys.argv[2]))
except Parsed:
    pass
else:
    raise AssertionError("CLI did not parse arguments")
"""
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(root / "ci/project"))
        with mock.patch.object(Path, "open", side_effect=AssertionError("inert helper opened an input")), \
                mock.patch.object(Path, "resolve", side_effect=AssertionError("inert helper resolved an input")):
            rows = runner.stage_specs(self.paths, self.revision, sys.executable, "f" * 64)
            runner.clean_environment(self.paths, sys.executable)
        for row in rows:
            with self.subTest(stage=row["id"]):
                result = subprocess.run([sys.executable, "-B", "-c", program, Path(row["argv"][2]).stem,
                    json.dumps(row["argv"][3:])], cwd=root, env=environment, capture_output=True,
                    text=True, timeout=15, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")
        argv = [item for key, value in vars(self.args).items() for item in ("--" + key.replace("_", "-"), str(value))]
        self.assertEqual(runner.argument_parser().parse_args(argv).expected_revision, self.revision)
        for flag in ("--source-dir", "--workspace-dir", "--expected-revision", "--archive-root",
                     "--dependency-repositories", "--host-bin", "--diagnostic-archive", "--control-archive"):
            index = argv.index(flag)
            with self.subTest(required=flag), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    runner.argument_parser().parse_args(argv[:index] + argv[index + 2:])


class QualifiedWarmFrozenWrapperInputsTests(unittest.TestCase):
    def test_fixed_archive_population_and_budget_values_match_existing_contracts(self):
        original = runner.qualification.base_proof()
        for name, proof_field in (("diagnostic_archive", "diagnostics"), ("control_archive", "controls")):
            self.assertEqual(runner.ORIGINAL_ARCHIVES[name], {key: original[proof_field]["archive"][key]
                                                            for key in ("sha256", "size_bytes")})
        self.assertEqual(runner.COMPLETE_COUNTS, runner.qualification.COMPLETE_COUNTS)
        self.assertEqual((runner.COMPLETE_COUNTS["processes"], runner.COMPLETE_COUNTS["launches"],
                          runner.COMPLETE_COUNTS["checked_words"]), (24, 792, 25344))
        self.assertEqual(runner.BUDGET["execution_timeout_seconds"], 5400)
        self.assertEqual({key: value for key, value in runner.BUDGET.items() if key != "execution_timeout_seconds"},
                         runner.dependency.BUDGET)


if __name__ == "__main__":
    unittest.main()
