# SPDX-License-Identifier: Apache-2.0
"""Qualification orchestration with synthetic producers and real digest bindings."""

from contextlib import redirect_stderr
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import p06_counter_qualification_admission as admission
import p06_counter_qualification_contract as contract
import p06_counter_qualification_execute as runner
import p06_dependency_admission as dependency_admission
import p06_managed_preflight_execute as preflight
from test_p06_dependency_admission import DependencyHarness
from test_p06_managed_preflight_runner import FIRST, HASH


ROOT = preflight.ROOT


class SyntheticAdmission:
    """Isolate orchestration from separately tested native prerequisite replay."""

    def __init__(self, path, expected_sha256, *, source, expected_revision,
                 dependency_admission, diagnostic_archive, diagnostic_sha256,
                 control_archive, control_sha256):
        self.path = Path(path)
        self.proof = contract.load_proof(self.path, expected_sha256)
        body = self.path.read_bytes()
        self.identity = {"path": str(self.path), "sha256": hashlib.sha256(body).hexdigest(),
                         "size_bytes": len(body)}
        self.helper_sources = HASH(source, ["tests/unittest/pending_reads/main.cpp"])
        self.prerequisite_inputs = []
        self.summary = {"scope": "synthetic-orchestration-only",
                        "proof_sha256": expected_sha256}
        self.before_stability = lambda: None
        self.verify_stable()

    def verify_stable(self):
        self.before_stability()
        body = self.path.read_bytes()
        if hashlib.sha256(body).hexdigest() != self.identity["sha256"]:
            raise ValueError("qualification original changed after admission")
        return {"proof_sha256": self.identity["sha256"],
                "helper_sources_sha256": contract.digest(self.helper_sources)}


class QualifiedHarness(DependencyHarness):
    def __enter__(self):
        super().__enter__()
        for relative in (*admission.SOURCE_FILES, "tests/unittest/pending_reads/main.cpp"):
            path = self.paths["source"] / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / relative).read_bytes())
        self.source_names = sorted(set(self.source_names) | set(admission.SOURCE_FILES))
        self.helper_names = sorted(set(self.helper_names) | {
            name for name in admission.SOURCE_FILES if name.endswith(".py")})
        self.helpers = HASH(self.paths["source"], self.helper_names)
        preflight.loaded_helpers.return_value = self.helpers
        self.proof_path = self.paths["source"].parent / "external-proof.json"
        self.proof_path.write_bytes((ROOT / contract.SOURCE_PROOF_PATH).read_bytes())
        self.args.counter_qualification = self.proof_path
        self.args.counter_qualification_sha256 = contract.SOURCE_PROOF_SHA256
        self.args.diagnostic_archive = self.paths["source"].parent / "diagnostic.zip"
        self.args.diagnostic_archive_sha256 = "d" * 64
        self.args.control_archive = self.paths["source"].parent / "controls.zip"
        self.args.control_archive_sha256 = "c" * 64
        self.admitted = None
        self.after_admission = lambda value: None

        def admit(*args, **kwargs):
            self.admitted = SyntheticAdmission(*args, **kwargs)
            self.after_admission(self.admitted)
            return self.admitted

        self.admit = self.stack.enter_context(mock.patch.object(admission, "Admission", side_effect=admit))
        return self

    def run(self):
        result = runner.execute(self.args, self.paths)
        self.saved = json.loads((self.paths["output"] / "report.json").read_text())
        return result


class QualificationRunnerTests(unittest.TestCase):
    def assert_finished(self, fixture, result, *, passed):
        self.assertEqual(result, fixture.saved)
        self.assertEqual(result["state"], "finished")
        self.assertEqual(result["contract_id"], contract.CONTRACT_ID)
        self.assertEqual(result["scope"], contract.SCOPE)
        self.assertIs(result["counter_qualification_passed"], passed)
        self.assertTrue(all(result[name] is False for name in contract.FALSE_CLAIMS))
        if not passed:
            self.assertIn(result["outcome"], ("blocked", "fail"))
            self.assertTrue(result["failures"])

    def test_complete_route_binds_before_launch_and_keeps_inner_claims_false(self):
        observed = []
        with QualifiedHarness() as fixture:
            original_command = fixture.command

            def inspect(argv, cwd, environment, logfile, **budget):
                if logfile.stem.startswith("preflight-"):
                    report = json.loads((fixture.paths["output"] / "report.json").read_text())
                    row = report["processes"][-1]
                    binding = fixture.retained(row["binding"])
                    self.assertEqual(binding["counter_qualification_sha256"], contract.SOURCE_PROOF_SHA256)
                    self.assertEqual(binding["build"]["counter_qualification_sha256"], contract.SOURCE_PROOF_SHA256)
                    self.assertEqual(binding["build"]["counter_qualification_admission"], fixture.admitted.summary)
                    self.assertEqual(preflight.qualification_id(binding), row["execution_binding_sha256"])
                    self.assertEqual(preflight.qualification_id(binding["build"]), row["build_binding_sha256"])
                    self.assertEqual(argv[argv.index("--qualification-id") + 1], row["execution_binding_sha256"])
                    altered = copy.deepcopy(binding)
                    altered.pop("counter_qualification_sha256")
                    self.assertNotEqual(preflight.qualification_id(altered), row["execution_binding_sha256"])
                    altered = copy.deepcopy(binding["build"])
                    altered.pop("counter_qualification_sha256")
                    self.assertNotEqual(preflight.qualification_id(altered), row["build_binding_sha256"])
                    observed.append(row["id"])
                return original_command(argv, cwd, environment, logfile, **budget)

            preflight.run_bounded.side_effect = inspect
            result = fixture.run()
            self.assert_finished(fixture, result, passed=True)
            self.assertEqual(observed, [row["id"] for row in preflight.manifest.process_plan()])
            self.assertEqual(result["completed_counts"], contract.COMPLETE_COUNTS)
            self.assertEqual(len(result["commands"]), 37)
            self.assertEqual(result["counter_qualification_admission_before"],
                             result["counter_qualification_admission_after"])
            self.assertTrue(all(row["counter_qualification_admission"]
                                == result["counter_qualification_admission_before"]
                                for row in result["stability_checks"]))
            self.assertEqual(fixture.retained(result["contract_snapshot"]), contract.contract())
            self.assertEqual(result["contract_sha256"], contract.contract_hash())
            retained = result["retained_counter_qualification"]
            self.assertEqual(retained["path"], "artifacts/counter-qualification/proof.json")
            self.assertEqual(retained["sha256"], contract.SOURCE_PROOF_SHA256)
            self.assertEqual((fixture.paths["output"] / retained["path"]).read_bytes(), fixture.proof_path.read_bytes())
            self.assertIn(retained, result["retained_files"])
            source = fixture.retained(result["source_before"])
            self.assertIn("tests/unittest/pending_reads/main.cpp", {row["path"] for row in source["files"]})
            for process in result["processes"]:
                for name in contract.FALSE_CLAIMS:
                    self.assertIs(process["observation"]["witness"][name], False)

    def test_bad_proof_pin_prevents_every_command(self):
        with QualifiedHarness() as fixture:
            fixture.args.counter_qualification_sha256 = "0" * 64
            result = fixture.run()
            self.assert_finished(fixture, result, passed=False)
            self.assertIn("independently selected", result["reason"])
            self.assertEqual(result["commands"], [])
            self.assertEqual(result["native_execution"], "not_run")
            self.assertEqual(fixture.calls, [])

    def test_semantically_changed_proof_prevents_every_command(self):
        with QualifiedHarness() as fixture:
            fixture.proof_path.write_bytes(fixture.proof_path.read_bytes().replace(b'"workers": 1', b'"workers": 2'))
            result = fixture.run()
            self.assert_finished(fixture, result, passed=False)
            self.assertEqual(result["commands"], [])
            self.assertEqual(result["native_execution"], "not_run")

    def test_qualification_drift_before_first_native_launch_stops_execution(self):
        with QualifiedHarness() as fixture:
            def mutate(name, build):
                if name == "version-gpp":
                    fixture.proof_path.write_bytes(fixture.proof_path.read_bytes() + b"\n")

            fixture.after_command = mutate
            result = fixture.run()
            self.assert_finished(fixture, result, passed=False)
            self.assertIn("qualification original changed", result["reason"])
            self.assertEqual(fixture.launches(), [])
            self.assertEqual(len(result["commands"]), 1)

    def test_between_policy_drift_stops_remaining_native_processes(self):
        with QualifiedHarness() as fixture:
            def mutate(name, build):
                if name == FIRST:
                    fixture.proof_path.write_bytes(fixture.proof_path.read_bytes() + b"\n")

            fixture.after_command = mutate
            result = fixture.run()
            self.assert_finished(fixture, result, passed=False)
            self.assertEqual(fixture.launches(), [FIRST])
            self.assertIn("qualification original changed", result["reason"])

    def test_final_only_qualification_drift_invalidates_complete_population(self):
        with QualifiedHarness() as fixture:
            def hook(admitted):
                def mutate():
                    path = fixture.paths["output"] / "report.json"
                    report = json.loads(path.read_text()) if path.exists() else {}
                    variants = report.get("variants", [])
                    if len(variants) == 2 and all(row["outcome"] == "pass" for row in variants):
                        fixture.proof_path.write_bytes(fixture.proof_path.read_bytes() + b"\n")
                admitted.before_stability = mutate

            fixture.after_admission = hook
            result = fixture.run()
            self.assert_finished(fixture, result, passed=False)
            self.assertEqual(len(fixture.launches()), 4)
            self.assertEqual(result["completed_counts"], contract.COMPLETE_COUNTS)
            self.assertEqual(result["failures"][0]["stage"], "final-counter-qualification-admission")

    def test_original_failure_stays_primary_with_final_admission_failure(self):
        with QualifiedHarness() as fixture:
            fixture.results[FIRST] = {"outcome": "fail", "reason": "original-exit37", "exit_code": 37}

            def mutate(name, build):
                if name == FIRST:
                    fixture.proof_path.write_bytes(fixture.proof_path.read_bytes() + b"\n")

            fixture.after_command = mutate
            result = fixture.run()
            self.assert_finished(fixture, result, passed=False)
            self.assertIn("original-exit37", result["reason"])
            self.assertTrue(any(row["stage"] == "final-counter-qualification-admission" for row in result["failures"]))

    def test_legacy_dependency_route_has_no_qualification_fields(self):
        with DependencyHarness() as fixture:
            result = fixture.run()
            self.assertEqual(result["outcome"], "pass")
            self.assertEqual(result["contract_id"], dependency_admission.CONTRACT_ID)
            self.assertFalse(any(name.startswith("counter_qualification") for name in result))
            for process in result["processes"]:
                binding = fixture.retained(process["binding"])
                self.assertNotIn("counter_qualification_sha256", binding)
                self.assertNotIn("counter_qualification_sha256", binding["build"])

    def test_mode_requires_exact_boolean_and_both_older_modes(self):
        for options in ({"counter_qualification": True}, {"lifetime": True, "counter_qualification": True},
                        {"lifetime": True, "dependency": True, "counter_qualification": 1},
                        {"lifetime": True, "dependency": True, "counter_qualification": "true"}):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, "counter qualification requires"):
                preflight.execute(None, None, **options)

    def test_old_cli_imports_do_not_load_qualification_helpers(self):
        for module in ("p06_managed_preflight_execute", "p06_native_lifetime_execute", "p06_dependency_lifetime_execute"):
            code = "\n".join(("import sys", "sys.path.insert(0, " + repr(str(ROOT / "ci/project")) + ")",
                "import " + module,
                "assert not any(name.startswith('p06_counter_qualification') for name in sys.modules)"))
            with self.subTest(module=module):
                result = subprocess.run([sys.executable, "-I", "-B", "-c", code],
                    capture_output=True, text=True, timeout=30, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_requires_each_explicit_qualification_input(self):
        argv = ["run", "--tools-dir", "/tools", "--work-dir", "/work", "--output", "/output",
            "--expected-revision", "a" * 40, "--dependency-receipt", "/dependency.json",
            "--dependency-receipt-sha256", "d" * 64]
        options = [("--counter-qualification", "/proof.json"),
            ("--counter-qualification-sha256", contract.SOURCE_PROOF_SHA256),
            ("--diagnostic-archive", "/diagnostic.zip"), ("--diagnostic-archive-sha256", "c" * 64),
            ("--control-archive", "/controls.zip"), ("--control-archive-sha256", "b" * 64)]
        runner.argument_parser().parse_args(argv + [item for pair in options for item in pair])
        for omitted in options:
            selected = argv + [item for pair in options if pair != omitted for item in pair]
            with self.subTest(omitted=omitted[0]), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                runner.argument_parser().parse_args(selected)


if __name__ == "__main__":
    unittest.main()
