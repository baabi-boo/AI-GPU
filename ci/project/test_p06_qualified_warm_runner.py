# SPDX-License-Identifier: Apache-2.0
"""Qualified warm orchestration with synthetic commands and real record checks."""

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

import p06_managed_preflight_execute as preflight
import p06_native_lifetime_test_fixture as samples
import p06_qualified_warm_admission as admission
import p06_qualified_warm_contract as contract
import p06_qualified_warm_execute as runner
import p06_qualified_warm_records as records
from test_p06_dependency_admission import DependencyHarness
from test_p06_managed_preflight_runner import HASH


ROOT = preflight.ROOT
FIRST = "warm-simx-fp16-pair0-per_operation"


class SyntheticAdmission:
    """Isolate producer orchestration from the separate prerequisite readers."""

    def __init__(self, path, expected_sha256, *, source, **_):
        self.path = Path(path)
        self.proof = contract.load_proof(self.path, expected_sha256)
        body = self.path.read_bytes()
        self.identity = {"path": str(self.path), "sha256": hashlib.sha256(body).hexdigest(),
                         "size_bytes": len(body)}
        self.helper_sources = HASH(source, ["tests/unittest/pending_reads/main.cpp"])
        self.prerequisite_inputs = []
        self.summary = {"scope": "synthetic-qualified-warm-orchestration-only",
                        "proof_sha256": expected_sha256}
        self.before_stability = lambda: None
        self.verify_stable()

    def verify_stable(self):
        self.before_stability()
        if hashlib.sha256(self.path.read_bytes()).hexdigest() != self.identity["sha256"]:
            raise ValueError("qualified warm original changed after admission")
        return {"proof_sha256": self.identity["sha256"],
                "helper_sources_sha256": contract.digest(self.helper_sources)}


class WarmHarness(DependencyHarness):
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
        self.proof_path = self.paths["source"].parent / "warm-proof.json"
        self.proof_path.write_bytes((ROOT / contract.SOURCE_PROOF_PATH).read_bytes())
        self.args.counter_qualification = self.proof_path
        self.args.counter_qualification_sha256 = contract.SOURCE_PROOF_SHA256
        self.args.diagnostic_archive = self.paths["source"].parent / "diagnostic.zip"
        self.args.diagnostic_archive_sha256 = "d" * 64
        self.args.control_archive = self.paths["source"].parent / "controls.zip"
        self.args.control_archive_sha256 = "c" * 64
        self.admitted = None
        self.after_admission = lambda _: None
        self.plan = {row["id"]: row for row in contract.process_plan()}
        self.mutate_output = self.warm_output

        def admit(*args, **kwargs):
            self.admitted = SyntheticAdmission(*args, **kwargs)
            self.after_admission(self.admitted)
            return self.admitted

        self.stack.enter_context(mock.patch.object(admission, "Admission", side_effect=admit))
        self.warm_verify = self.stack.enter_context(mock.patch.object(records, "verify_output", wraps=records.verify_output))
        return self

    def warm_output(self, name, text):
        if name.startswith("warm-"):
            _, original = records.managed_records._split_output(text)
            planned = self.plan[name]
            _, operations, summary, witness, lifetime = samples.raw_records(
                original["format"], original["policy"], binding_id=original["execution_binding_sha256"])
            for row in (*operations, summary):
                row.update(sample_id=planned["sample_id"], pair_index=planned["pair_index"], phase=planned["phase"])
            for snapshot in summary["snapshots"].values():
                snapshot["sample_id"] = planned["sample_id"]
            summary["device_release"]["sample_id"] = planned["sample_id"]
            identity = records.process_identity(original["format"], original["policy"],
                original["execution_binding_sha256"], planned["pair_index"], planned["phase"])
            witness.update(identity)
            witness["loaded_libraries"] = original["loaded_libraries"]
            lifetime.update(identity, contract_id="p06-qualified-warm-lifetime-witness-v1")
            text = samples.render_log(operations, summary, witness, lifetime)
        return self.transform_output(name, text)

    def command(self, argv, *args, **kwargs):
        original = list(argv)
        translated = [value for value in original if value != "--qualified-warm"]
        try:
            return super().command(translated, *args, **kwargs)
        finally:
            if self.calls:
                self.calls[-1]["argv"] = original

    def launches(self):
        return [call["id"] for call in self.calls if call["id"].startswith("warm-")]

    def run(self):
        result = runner.execute(self.args, self.paths)
        self.saved = json.loads((self.paths["output"] / "report.json").read_text())
        return result


class QualifiedWarmRunnerTests(unittest.TestCase):
    def assert_finished(self, fixture, result, *, passed):
        self.assertEqual(result, fixture.saved)
        self.assertEqual(result["state"], "finished")
        self.assertEqual(result["contract_id"], contract.CONTRACT_ID)
        self.assertEqual(result["scope"], contract.SCOPE)
        self.assertIs(result["qualified_warm_passed"], passed)
        self.assertIs(result["counter_qualification_passed"], passed)
        self.assertTrue(all(result[name] is False for name in preflight.manifest.FALSE_CLAIMS))
        if not passed:
            self.assertIn(result["outcome"], ("blocked", "fail"))
            self.assertTrue(result["failures"])

    def test_all_24_processes_have_prelaunch_sampling_proof_and_same_format_build(self):
        observed = []
        plan = contract.process_plan()
        with WarmHarness() as fixture:
            original_command = fixture.command

            def inspect(argv, cwd, environment, logfile, **budget):
                if logfile.stem.startswith("warm-"):
                    report = json.loads((fixture.paths["output"] / "report.json").read_text())
                    row = report["processes"][-1]
                    binding = fixture.retained(row["binding"])
                    self.assertEqual(binding["counter_qualification_sha256"], contract.SOURCE_PROOF_SHA256)
                    self.assertEqual(binding["build"]["counter_qualification_admission"], fixture.admitted.summary)
                    self.assertEqual(binding["warm_sampling"], binding["build"]["warm_sampling"])
                    self.assertEqual(binding["warm_sampling"]["processes"], plan)
                    self.assertEqual(binding["warm_sampling"]["sampling"], preflight.warm_contract.load_contract()["sampling"])
                    self.assertEqual(binding["warm_sampling"]["contract_sha256"], preflight.manifest.WARM_CONTRACT_SHA256)
                    self.assertEqual(preflight.qualification_id(binding), row["execution_binding_sha256"])
                    self.assertEqual(preflight.qualification_id(binding["build"]), row["build_binding_sha256"])
                    self.assertEqual(argv[1:3], ["--lifetime", "--qualified-warm"])
                    for flag, wanted in (("--qualification-id", row["execution_binding_sha256"]),
                            ("--sample-id", row["sample_id"]), ("--pair-index", str(row["pair_index"])),
                            ("--phase", row["phase"])):
                        self.assertEqual(argv[argv.index(flag) + 1], wanted)
                    for field in ("warm_sampling", "counter_qualification_sha256"):
                        altered = copy.deepcopy(binding)
                        altered.pop(field)
                        self.assertNotEqual(preflight.qualification_id(altered), row["execution_binding_sha256"])
                    observed.append(row["id"])
                return original_command(argv, cwd, environment, logfile, **budget)

            preflight.run_bounded.side_effect = inspect
            result = fixture.run()
            self.assert_finished(fixture, result, passed=True)
            self.assertEqual(observed, [row["id"] for row in plan])
            self.assertEqual(fixture.launches(), observed)
            self.assertEqual(result["completed_counts"], contract.COMPLETE_COUNTS)
            self.assertEqual(len(result["commands"]), 57)
            self.assertEqual(fixture.warm_verify.call_count, 24)
            self.assertEqual(len({row["execution_binding_sha256"] for row in result["processes"]}), 24)
            self.assertEqual(len({row["build_binding_sha256"] for row in result["processes"]}), 2)
            self.assertEqual(fixture.retained(result["contract_snapshot"]), contract.contract())
            self.assertEqual(result["counter_qualification_admission_before"], result["counter_qualification_admission_after"])

    def test_wrong_proof_pin_prevents_all_commands(self):
        with WarmHarness() as fixture:
            fixture.args.counter_qualification_sha256 = "0" * 64
            result = fixture.run()
            self.assert_finished(fixture, result, passed=False)
            self.assertEqual(result["commands"], [])
            self.assertEqual(result["native_execution"], "not_run")

    def test_drift_after_first_process_stops_complete_attempt_without_replacement(self):
        with WarmHarness() as fixture:
            def mutate(name, _):
                if name == FIRST:
                    fixture.proof_path.write_bytes(fixture.proof_path.read_bytes() + b"\n")
            fixture.after_command = mutate
            result = fixture.run()
            self.assert_finished(fixture, result, passed=False)
            self.assertEqual(fixture.launches(), [FIRST])
            self.assertEqual(result["completed_counts"]["processes"], 0)
            self.assertIn("changed after admission", result["reason"])

    def test_failed_measured_sample_retains_prior_population_and_stops(self):
        plan = contract.process_plan()
        failed = plan[3]["id"]
        with WarmHarness() as fixture:
            fixture.results[failed] = {"outcome": "fail", "reason": "injected-exit37", "exit_code": 37}
            result = fixture.run()
            self.assert_finished(fixture, result, passed=False)
            self.assertEqual(fixture.launches(), [row["id"] for row in plan[:4]])
            self.assertEqual(result["completed_counts"]["processes"], 3)
            self.assertIn("injected-exit37", result["reason"])
            self.assertEqual(result["processes"][-1]["outcome"], "fail")

    def test_interruption_retains_started_process_and_does_not_retry(self):
        with WarmHarness() as fixture:
            fixture.exceptions[FIRST] = KeyboardInterrupt()
            result = fixture.run()
            self.assert_finished(fixture, result, passed=False)
            self.assertEqual(fixture.launches(), [FIRST])
            self.assertEqual(result["native_execution"], "unknown")
            self.assertEqual(result["reason"], "interrupted")

    def test_cross_pair_raw_transcript_fails(self):
        with WarmHarness() as fixture:
            def corrupt(name, text):
                if name == FIRST:
                    return text.replace('"pair_index":0', '"pair_index":1')
                return text
            fixture.transform_output = corrupt
            result = fixture.run()
            self.assert_finished(fixture, result, passed=False)
            self.assertEqual(fixture.launches(), [FIRST])
            self.assertEqual(result["completed_counts"]["processes"], 0)

    def test_mode_requires_exact_boolean_and_all_prerequisites(self):
        for options in ({"qualified_warm": True}, {"lifetime": True, "qualified_warm": True},
                {"lifetime": True, "dependency": True, "qualified_warm": True},
                {"lifetime": True, "dependency": True, "counter_qualification": True, "qualified_warm": 1},
                {"lifetime": True, "dependency": True, "counter_qualification": True, "qualified_warm": "true"}):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, "qualified warm execution requires"):
                preflight.execute(None, None, **options)

    def test_historical_imports_do_not_select_warm_helpers(self):
        for module in ("p06_managed_preflight_execute", "p06_native_lifetime_execute",
                       "p06_dependency_lifetime_execute", "p06_counter_qualification_execute"):
            code = "\n".join(("import sys", "sys.path.insert(0, " + repr(str(ROOT / "ci/project")) + ")",
                "import " + module,
                "assert not any(name.startswith('p06_qualified_warm') for name in sys.modules)"))
            with self.subTest(module=module):
                result = subprocess.run([sys.executable, "-I", "-B", "-c", code],
                    capture_output=True, text=True, timeout=30, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_requires_all_explicit_prerequisites(self):
        argv = ["run", "--tools-dir", "/tools", "--work-dir", "/work", "--output", "/output",
            "--expected-revision", "a" * 40, "--dependency-receipt", "/dependency.json",
            "--dependency-receipt-sha256", "d" * 64]
        options = [("--counter-qualification", "/proof.json"),
            ("--counter-qualification-sha256", contract.SOURCE_PROOF_SHA256),
            ("--diagnostic-archive", "/diagnostics.zip"), ("--diagnostic-archive-sha256", "d" * 64),
            ("--control-archive", "/controls.zip"), ("--control-archive-sha256", "c" * 64)]
        for missing in range(len(options)):
            selected = argv + [word for index, pair in enumerate(options) if index != missing for word in pair]
            with self.subTest(missing=options[missing][0]), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                runner.argument_parser().parse_args(selected)


if __name__ == "__main__":
    unittest.main()
