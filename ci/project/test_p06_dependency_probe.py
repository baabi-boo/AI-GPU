# SPDX-License-Identifier: Apache-2.0
"""Host-only checks for explicit fresh-dependency pending-probe admission."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import p06_dependency_contract as contract
import p06_pending_probe as probe
from p06_managed_preflight_build_fixture import generate
from test_p06_pending_probe import ProbeHarness, REVISION


ROOT = Path(__file__).resolve().parents[2]
PIN = "d" * 64


class DependencyProbeHarness(ProbeHarness):
    """Synthetic execution with real retained files, compiler stamps and hashes."""

    def __enter__(self):
        super().__enter__()
        self.args.dependency_receipt_sha256 = PIN
        self.build_names = probe.preflight.artifacts(self.build, dependency=True)
        for name in self.build_names:
            path = self.build / name
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic dependency build artifact: " + name.encode())
        self.bind_artifacts()
        self.report.update(contract_id=contract.MANAGED_CONTRACT_ID,
            dependency_receipt_sha256=PIN, dependency_source_to_loaded_binary_verified=True,
            completed_counts=dict(probe.preflight.COMPLETE_COUNTS),
            processes=[{"id": "preflight-simx-" + fmt + "-" + policy,
                        "format": fmt, "policy": policy, "backend": "simx", "outcome": "pass"}
                       for fmt in ("fp16", "bf16")
                       for policy in ("per_operation", "reusable_single_tile")])
        self.variant.update(dependency_receipt_sha256=PIN,
            application_build_records={"synthetic_application_commands": 30},
            dependency_model_link={"synthetic_softfloat_members": ["member.o"]})
        self.binding = {"contract_id": contract.MANAGED_CONTRACT_ID,
            "dependency_receipt_sha256": PIN, "artifacts": self.variant["artifacts_before"],
            "format": self.data["fmt"], "backend": "simx",
            **dict.fromkeys(contract.FALSE_CLAIMS, False),
            "application_build_records": copy.deepcopy(self.variant["application_build_records"]),
            "dependency_model_link": copy.deepcopy(self.variant["dependency_model_link"])}
        self.binding_path = self.managed / "snapshots" / (
            "simx-" + self.data["fmt"] + "-build-binding.json")
        self.bind_selected_build()
        return self

    def bind_selected_build(self):
        self.binding_path.write_text(json.dumps(self.binding))
        relative = self.binding_path.relative_to(self.managed).as_posix()
        self.variant["binding"] = probe.hash_artifacts(self.managed, [relative])[0]
        self.variant["build_binding_sha256"] = probe.preflight.qualification_id(self.binding)


class DependencyProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="dependency-probe-stamps-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.generated = generate(Path(cls.temporary.name))

    def setUp(self):
        self.data = self.generated["formats"]["fp16"]

    def assert_blocked(self, fixture, reason):
        result = fixture.run()
        self.assertEqual(result["outcome"], "blocked", result["reason"])
        self.assertEqual(result["state"], "finished")
        self.assertEqual(result["native_execution"], "not_run")
        self.assertIs(result["native_probe_passed"], False)
        self.assertIn(reason, result["reason"])
        self.assertEqual(result, fixture.saved)
        fixture.executor.assert_not_called()
        for name in contract.FALSE_CLAIMS:
            self.assertIs(result[name], False)

    def test_default_parser_and_imports_do_not_select_dependency_contract(self):
        args = probe.argument_parser().parse_args([
            "--build-dir", "/build", "--managed-report", "/report.json",
            "--output-dir", "/output", "--expected-revision", REVISION])
        self.assertIsNone(args.dependency_receipt_sha256)
        body = ("import sys\nimport p06_pending_probe\n"
                "assert 'p06_dependency_contract' not in sys.modules\n"
                "assert 'p06_dependency_receipt' not in sys.modules\n"
                "assert 'p06_dependency_admission' not in sys.modules\n")
        result = subprocess.run([sys.executable, "-c", body], cwd=ROOT,
            env=dict(os.environ, PYTHONPATH=str(ROOT / "ci/project"), PYTHONDONTWRITEBYTECODE="1"),
            text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_each_contract_requires_its_own_explicit_route(self):
        with DependencyProbeHarness(self.data) as fixture:
            fixture.args.dependency_receipt_sha256 = None
            self.assert_blocked(fixture, "completed managed lifetime")
        with ProbeHarness(self.data) as fixture:
            fixture.args.dependency_receipt_sha256 = PIN
            self.assert_blocked(fixture, "completed managed lifetime")

    def test_explicit_pin_requires_canonical_sha256_before_execution(self):
        for pin in ("", "0" * 63, "0" * 65, "A" * 64, "g" * 64, 1, True):
            with self.subTest(pin=pin), DependencyProbeHarness(self.data) as fixture:
                fixture.args.dependency_receipt_sha256 = pin
                self.assert_blocked(fixture, "not an exact SHA256")

    def test_completed_dependency_route_retains_binding_and_keeps_probe_separate(self):
        for fmt, data in self.generated["formats"].items():
            with self.subTest(fmt=fmt), DependencyProbeHarness(data) as fixture:
                result = fixture.run()
                self.assertEqual(result["outcome"], "pass", result["reason"])
                self.assertIs(result["native_probe_passed"], True)
                self.assertIs(result["zero_mutation_rejected"], True)
                self.assertEqual(result["dependency_receipt_sha256"], PIN)
                self.assertEqual(result["managed_contract_id"], contract.MANAGED_CONTRACT_ID)
                self.assertEqual(result["inputs_before"], result["inputs_after"])
                snapshots = [row["path"] for row in result["inputs_before"]["managed_snapshots"]]
                self.assertIn("snapshots/simx-" + fmt + "-build-binding.json", snapshots)
                self.assertEqual([row["id"] for row in fixture.calls], ["compiler-version",
                    "compile-native", "run-native", "compile-always-zero", "run-always-zero"])
                self.assertNotIn("dependency_source_to_loaded_binary_verified", result)
                self.assertNotIn("completed_counts", result)
                for flag in contract.FALSE_CLAIMS:
                    self.assertIs(result[flag], False)
                for call in fixture.calls:
                    self.assertEqual(call["environment"]["THREADS"], "1")
                    for name, expected in probe.BUDGET.items():
                        self.assertEqual(call[name], expected)

    def test_admission_rejects_false_pass_flags_wrong_revision_and_receipt(self):
        changes = [("contract_id", probe.MANAGED_CONTRACT_ID), ("state", "running"),
            ("outcome", "blocked"), ("native_lifetime_passed", 1),
            ("native_preflight_passed", False), ("expected_revision", "b" * 40),
            ("dependency_source_to_loaded_binary_verified", 1),
            ("dependency_source_to_loaded_binary_verified", False),
            ("dependency_receipt_sha256", "e" * 64)]
        changes.extend((flag, True) for flag in contract.FALSE_CLAIMS)
        for name, value in changes:
            with self.subTest(name=name, value=value), DependencyProbeHarness(self.data) as fixture:
                fixture.report[name] = value
                self.assert_blocked(fixture, "")

    def test_population_cannot_be_partial_duplicated_reordered_or_relabelled(self):
        changes = [lambda report: report["processes"].pop(),
            lambda report: report["processes"].append(copy.deepcopy(report["processes"][0])),
            lambda report: report["processes"].reverse(),
            lambda report: report["processes"][0].update(outcome="running"),
            lambda report: report["processes"][0].update(format="bf16"),
            lambda report: report["processes"][0].update(backend="rtlsim"),
            lambda report: report["completed_counts"].update(processes=True),
            lambda report: report["completed_counts"].update(launches=131),
            lambda report: report["completed_counts"].update(extra=0)]
        for change in changes:
            with self.subTest(change=change), DependencyProbeHarness(self.data) as fixture:
                change(fixture.report)
                self.assert_blocked(fixture, "population")

    def test_selected_binding_requires_retained_bytes_and_its_semantic_identity(self):
        for change in (lambda fixture: fixture.binding_path.write_text("{}"),
                       lambda fixture: fixture.variant.update(build_binding_sha256="f" * 64),
                       lambda fixture: fixture.variant["binding"].update(path="snapshots/foreign.json")):
            with self.subTest(change=change), DependencyProbeHarness(self.data) as fixture:
                change(fixture)
                self.assert_blocked(fixture, "")

    def test_rehashed_binding_cannot_substitute_receipt_application_or_model(self):
        for name, value in (("contract_id", probe.MANAGED_CONTRACT_ID),
                            ("dependency_receipt_sha256", "e" * 64),
                            ("format", "fp32"), ("backend", "rtlsim"), ("qualified", True),
                            ("application_build_records", {}), ("dependency_model_link", {}),
                            ("artifacts", [])):
            with self.subTest(name=name), DependencyProbeHarness(self.data) as fixture:
                fixture.binding[name] = value
                fixture.bind_selected_build()
                self.assert_blocked(fixture, "")
        with DependencyProbeHarness(self.data) as fixture:
            fixture.variant["dependency_receipt_sha256"] = "e" * 64
            self.assert_blocked(fixture, "caller dependency receipt")

    def test_dependency_model_recipe_and_map_are_frozen_live_inputs(self):
        for name in ("tests/regression/ai_counter_preflight/dependency_model.mk",
                     "sw/runtime/dependency-model.map"):
            with self.subTest(name=name), DependencyProbeHarness(self.data) as fixture:
                (fixture.build / name).write_bytes(b"substituted dependency link input")
                self.assert_blocked(fixture, "model products or generated inputs")

    def test_binding_and_map_changes_during_execution_preserve_first_failure(self):
        for target in ("binding", "map"):
            with self.subTest(target=target), DependencyProbeHarness(self.data) as fixture:
                path = fixture.binding_path if target == "binding" else fixture.build / "sw/runtime/dependency-model.map"
                fixture.results["compiler-version"] = {"outcome": "fail", "exit_code": 17,
                                                        "reason": "synthetic_compiler_failure"}
                fixture.after_command = lambda name: path.write_bytes(b"changed after command")
                result = fixture.run()
                self.assertEqual(result["outcome"], "fail")
                self.assertIn("synthetic_compiler_failure", result["reason"])
                self.assertIn("probe input stability failed", result["failures"])
                self.assertEqual(len(fixture.calls), 1)
                self.assertIs(result["native_probe_passed"], False)


if __name__ == "__main__":
    unittest.main()
