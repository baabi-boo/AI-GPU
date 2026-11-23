# SPDX-License-Identifier: Apache-2.0
"""Exercise local orchestration boundaries without simulating GPU acceptance."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from baseline_process import LIMITATIONS as PROCESS_LIMITATIONS
import p06_dependency_contract as contract
import p06_dependency_local_execute as execute


class LocalExecutionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-local-execute-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source, self.archives, self.repositories, self.host = [self.root / name
            for name in ("source", "archives", "repositories", "host-bin")]
        for path in (self.source, self.archives, self.repositories, self.host):
            path.mkdir()
        self.workspace = self.root / "attempt"
        self.revision = "a" * 40
        script = self.source / execute.SOURCE_FILE
        script.parent.mkdir(parents=True)
        script.write_bytes(Path(execute.__file__).read_bytes())
        self.args = SimpleNamespace(source_dir=self.source, workspace_dir=self.workspace,
            expected_revision=self.revision, archive_root=self.archives,
            dependency_repositories=self.repositories, host_bin=self.host)
        self.checkout = {"revision": self.revision, "dirty": False, "blockers": []}
        self.interpreter = dict(execute.interpreter_identity(), python_version=[3, 12, 14],
                                implementation="CPython", platform="linux")
        self.paths = {"source": str(self.source), "workspace": str(self.workspace),
            "archive": str(self.archives), "repositories": str(self.repositories), "host_bin": str(self.host)}
        self.observed = []
        self.change = None
        for patch in (
            mock.patch.object(execute, "ROOT", self.source),
            mock.patch.object(execute, "collect_source", side_effect=lambda root: deepcopy(self.checkout)),
            mock.patch.object(execute, "interpreter_identity", side_effect=lambda: deepcopy(self.interpreter)),
            mock.patch.object(execute.shutil, "disk_usage", return_value=SimpleNamespace(free=50 * 2**30)),
            mock.patch.object(execute, "available_memory_bytes", return_value=8 * 2**30),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def child(self, argv, cwd, environment, log, **limits):
        name = log.stem
        self.observed.append({"id": name, "argv": argv, "cwd": cwd, "environment": environment, "limits": limits})
        evidence = self.workspace / "evidence"
        identifiers = {"preparation": "p06-local-dependency-preparation-v1",
            "dependency-build": "p06-dependency-provenance-v1",
            "native-lifetime": "p06-managed-dependency-lifetime-v1",
            "pending-probe": "p06-pending-read-probe-v1",
            "dependency-substitution": "p06-dependency-substitution-control-v1"}
        document = {"schema_version": 1, "contract_id": identifiers[name], "expected_revision": self.revision,
            "state": "finished", "outcome": "pass", "reason": None, "failures": [],
            **dict.fromkeys(contract.FALSE_CLAIMS, False)}
        relative = "dependency-preparation.json" if name == "preparation" else name + "/report.json"
        if name == "preparation":
            document.update(execution_origin="local", native_execution="not_run")
        elif name == "dependency-build":
            document["fresh_dependency_build_passed"] = True
        else:
            dependency_body = (evidence / "dependency-build/report.json").read_bytes()
            document.update(native_execution="run", dependency_receipt_sha256=hashlib.sha256(dependency_body).hexdigest())
            if name == "native-lifetime":
                body = json.dumps({"checkout": self.checkout}).encode()
                path = evidence / "native-lifetime/snapshots/source-before.json"
                path.parent.mkdir(parents=True)
                path.write_bytes(body)
                document.update(native_preflight_passed=True, native_lifetime_passed=True,
                    dependency_source_to_loaded_binary_verified=True, completed_counts=dict(execute.COMPLETE_COUNTS),
                    source_before={"path": "snapshots/source-before.json", "sha256": hashlib.sha256(body).hexdigest(),
                                   "size_bytes": len(body)})
            elif name == "pending-probe":
                document.update(native_probe_passed=True, zero_mutation_rejected=True)
            else:
                document.update(control_passed=True, alternate_dependency_built=True,
                    numerical_control_passed=True, original_provenance_rejected=True,
                    control_counts={"processes": 1, "launches": 33, "checked_words": 1056})
        return_code = self.change(name, document, argv) if self.change else 0
        path = evidence / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document) + "\n")
        body = (json.dumps(execute.report_terminal(name, document, self.paths)) + "\n").encode()
        log.write_bytes(body)
        return {"process_started": True, "outcome": "pass" if return_code == 0 else "fail",
            "exit_code": return_code, "reason": None if return_code == 0 else "nonzero_exit",
            "duration_seconds": 0.001, "log_sha256": hashlib.sha256(body).hexdigest(),
            "log_size_bytes": len(body), "peak_rss_bytes": 1024, "cleanup_complete": True,
            "limitations": list(PROCESS_LIMITATIONS)}

    def run_route(self):
        with mock.patch.object(execute, "run_bounded", side_effect=self.child):
            result = execute.execute(self.args)
        retained = json.loads((self.workspace / "evidence/local-execution.json").read_text())
        self.assertEqual(result, retained)
        self.assertTrue(all(result[field] is False for field in contract.FALSE_CLAIMS))
        return result

    def test_five_separate_children_pin_reports_and_preserve_fixed_inner_budgets(self):
        result = self.run_route()
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual([row["id"] for row in self.observed], list(execute.STAGE_NAMES))
        self.assertEqual(set(result["reports"]), set(execute.STAGE_NAMES) | {"native-source"})
        self.assertEqual(result["execution_origin"], "local")
        self.assertFalse(any(name.startswith("GITHUB_") for name in result))
        pin = result["reports"]["dependency-build"]["sha256"]
        for row in self.observed:
            self.assertEqual(row["argv"][:2], [sys.executable, "-B"])
            self.assertEqual(row["cwd"], self.source)
            self.assertEqual(row["limits"]["max_rss_bytes"], 4 * 2**30)
            self.assertEqual(row["limits"]["min_free_bytes"], 15 * 2**30)
            self.assertLessEqual(row["limits"]["timeout_seconds"], 5400)
            self.assertEqual(row["environment"]["THREADS"], "1")
            if row["id"] in ("native-lifetime", "pending-probe", "dependency-substitution"):
                self.assertEqual(row["argv"][row["argv"].index("--dependency-receipt-sha256") + 1], pin)
        native = self.observed[2]["argv"]
        for flag, value in (("--jobs", "2"), ("--timeout-seconds", "1800"), ("--run-timeout-seconds", "180")):
            self.assertEqual(native[native.index(flag) + 1], value)

    def test_dirty_source_retains_blocked_original_before_any_child(self):
        self.checkout["dirty"] = True
        result = self.run_route()
        self.assertEqual(result["outcome"], "blocked")
        self.assertIn("clean source", result["reason"])
        self.assertEqual(self.observed, [])

    def test_wrong_source_revision_is_blocked(self):
        self.checkout["revision"] = "b" * 40
        self.assertIn("expected revision", self.run_route()["reason"])
        self.assertEqual(self.observed, [])

    def test_python_version_is_pinned(self):
        self.interpreter["python_version"] = [3, 12, 13]
        self.assertIn("3.12.14", self.run_route()["reason"])
        self.assertEqual(self.observed, [])

    def test_failed_child_is_retained_and_prevents_later_stages(self):
        def fail(name, document, argv):
            if name == "dependency-build":
                document.update(outcome="fail", reason="deliberate compile failure", failures=["compile"])
                return 9
            return 0
        self.change = fail
        result = self.run_route()
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(len(self.observed), 2)
        self.assertEqual(result["stages"][-1]["exit_code"], 9)
        self.assertIn("dependency-build", result["reports"])
        self.assertEqual(result["native_execution"], "not_run")

    def test_success_exit_cannot_promote_another_origin(self):
        self.change = lambda name, document, argv: document.update(execution_origin="github") or 0
        self.assertIn("local execution scope", self.run_route()["reason"])
        self.assertEqual(len(self.observed), 1)

    def test_wrong_native_population_is_rejected_with_execution_preserved(self):
        def change(name, document, argv):
            if name == "native-lifetime":
                document["completed_counts"]["launches"] = 131
            return 0
        self.change = change
        result = self.run_route()
        self.assertIn("fixed four-process", result["reason"])
        self.assertEqual(result["native_execution"], "run")
        self.assertEqual(len(self.observed), 3)

    def test_a_qualification_claim_is_rejected(self):
        self.change = lambda name, document, argv: document.update(qualified=True) or 0
        self.assertIn("non-acceptance", self.run_route()["reason"])

    def test_altered_earlier_report_prevents_successful_closeout(self):
        def change(name, document, argv):
            if name == "dependency-substitution":
                path = self.workspace / "evidence/dependency-preparation.json"
                path.write_bytes(path.read_bytes() + b" ")
            return 0
        self.change = change
        result = self.run_route()
        self.assertIn("changed after its stage", result["reason"])
        self.assertFalse(result["fresh_dependency_build_passed"])

    def test_source_change_at_final_boundary_is_not_a_pass(self):
        def change(name, document, argv):
            if name == "dependency-substitution":
                self.checkout["revision"] = "b" * 40
            return 0
        self.change = change
        self.assertIn("source changed", self.run_route()["reason"])

    def test_shared_deadline_stops_before_starting_another_child(self):
        clock = [0.0]
        def change(name, document, argv):
            clock[0] = 5401.0
            return 0
        self.change = change
        with mock.patch.object(execute.time, "monotonic", side_effect=lambda: clock[0]):
            result = self.run_route()
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("90-minute", result["reason"])
        self.assertEqual(len(self.observed), 1)
        self.assertEqual(result["duration_seconds"], 5401.0)

    def test_consistent_log_hash_cannot_hide_a_disagreeing_terminal(self):
        normal = self.child
        def child(argv, cwd, environment, log, **limits):
            result = normal(argv, cwd, environment, log, **limits)
            body = b'{"outcome":"pass","reason":null}\n'
            log.write_bytes(body)
            result.update(log_sha256=hashlib.sha256(body).hexdigest(), log_size_bytes=len(body))
            return result
        with mock.patch.object(execute, "run_bounded", side_effect=child):
            result = execute.execute(self.args)
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("terminal output differs", result["reason"])
        self.assertEqual(len(self.observed), 1)

    def test_native_monitor_exception_retains_unknown_execution(self):
        normal = self.child
        def child(argv, cwd, environment, log, **limits):
            if log.stem == "native-lifetime":
                raise OSError("monitor observation lost")
            return normal(argv, cwd, environment, log, **limits)
        with mock.patch.object(execute, "run_bounded", side_effect=child):
            result = execute.execute(self.args)
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["native_execution"], "unknown")
        self.assertIn("monitor observation lost", result["reason"])

    def test_existing_attempt_is_never_overwritten(self):
        self.run_route()
        path = self.workspace / "evidence/local-execution.json"
        original = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "fresh"):
            execute.execute(self.args)
        self.assertEqual(path.read_bytes(), original)

    def test_real_nonzero_child_is_observed_without_promoting_execution(self):
        path = self.source / "ci/project/p06_dependency_local_prepare.py"
        path.write_text('print("deliberate child failure")\nraise SystemExit(7)\n')
        result = execute.execute(self.args)
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["stages"][0]["exit_code"], 7)
        self.assertTrue(result["stages"][0]["process_started"])
        self.assertEqual(result["native_execution"], "not_run")
        self.assertEqual(len(result["stages"]), 1)
        self.assertEqual((self.workspace / "evidence/local-logs/preparation.log").read_text(),
                         "deliberate child failure\n")

    def test_command_and_environment_helpers_do_not_open_producer_paths(self):
        with mock.patch.object(Path, "open", side_effect=AssertionError("producer path read")), \
                mock.patch.object(Path, "resolve", side_effect=AssertionError("producer path resolution")):
            rows = execute.stage_specs(self.paths, self.revision, sys.executable, "f" * 64)
            environment = execute.clean_environment(self.paths, sys.executable)
        self.assertEqual(len(rows), 5)
        self.assertEqual(environment["MAKEFLAGS"], "-j2")


if __name__ == "__main__":
    unittest.main()
