# Licensed under the Apache License, Version 2.0.
"""Executing helper identity and workload claims over inert, file-backed fixtures."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import baseline_process
import local_qualification as runner
import local_qualification_inventory as inventory
from test_local_qualification_runner import RunnerFixture


IMPORT_MUTATION_PROBE = r'''
from argparse import Namespace
import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest import mock

helpers = Path(sys.argv[1])
sys.path.insert(0, str(helpers))
import local_qualification as runner
import local_qualification_cases as cases
import local_qualification_inventory as inventory

check = unittest.TestCase()
for module in (runner, cases, inventory):
    check.assertEqual(Path(module.__file__).parent, helpers)
args = Namespace(**json.loads(sys.argv[2]))
paths = runner.resolve_paths(args)
loaded_contract = runner.CONTRACT_ID
before = inventory.collect_helpers()
helper = helpers / "local_qualification_cases.py"
original = helper.read_text()
declaration = 'CONTRACT_ID = "' + loaded_contract + '"'
check.assertEqual(original.count(declaration), 1)
helper.write_text(original.replace(declaration, 'CONTRACT_ID = "edited-after-import"'))
check.assertNotEqual(inventory.collect_helpers(), before)
check.assertEqual(cases.CONTRACT_ID, loaded_contract)
check.assertEqual(runner.CONTRACT_ID, loaded_contract)
capacity = type(shutil.disk_usage(helpers))(64 * runner.GIB, runner.GIB, 63 * runner.GIB)
with mock.patch.object(shutil, "disk_usage", return_value=capacity):
    with mock.patch.object(runner, "run_bounded") as process:
        with check.assertRaisesRegex(ValueError, "helper identities changed after import"):
            runner.plan_run(args, paths)
        helper.write_text(original)
        restored = runner.plan_run(args, paths)
        check.assertEqual(restored["outcome"], "pass", restored["blockers"])
        check.assertEqual(restored["helpers_before"], before)
        process.assert_not_called()
check.assertFalse(paths["build"].exists())
check.assertFalse(paths["output"].exists())
print(json.dumps({"changed_helper_rejected": True, "restored_plan": restored["outcome"],
                  "execution_performed": restored["execution_performed"]}))
'''


MALFORMED_HELPER_PROBE = r'''
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import sys
import unittest
from unittest import mock

helpers = Path(sys.argv[1])
sys.path.insert(0, str(helpers))
import local_qualification as runner
import local_qualification_cases as cases
import local_qualification_inventory as inventory

check = unittest.TestCase()
for module in (runner, cases, inventory):
    check.assertEqual(Path(module.__file__).parent, helpers)
sys.path.append(sys.argv[2])
from test_local_qualification_runner import RunnerFixture

stage = sys.argv[3]
base = helpers.parent / ("malformed-" + stage)
base.mkdir()
fixture = RunnerFixture(base)
helper = helpers / "local_qualification_cases.py"
original = helper.read_bytes()
malformed = original + b"\ndef invalid_helper(:\n"
reason = "local helper has invalid Python syntax: " + helper.name
capacity = type(shutil.disk_usage(base))(64 * runner.GIB, runner.GIB, 63 * runner.GIB)
with mock.patch.dict(os.environ, fixture.environment, clear=True), \
        mock.patch.object(shutil, "disk_usage", return_value=capacity), \
        mock.patch.object(runner, "run_bounded", side_effect=fixture.command) as process, \
        mock.patch.object(runner, "verify_log", wraps=runner.verify_log) as oracle:
    try:
        if stage == "plan":
            fixture.args.mode = "plan"
            helper.write_bytes(malformed)
            with check.assertRaisesRegex(ValueError, reason):
                runner.plan_run(fixture.args, fixture.paths)
            argv = [fixture.args.mode]
            for name, value in vars(fixture.args).items():
                if name not in ("mode", "case"):
                    argv.extend(("--" + name.replace("_", "-"), str(value)))
            argv.extend(("--case", "cp-llc-port"))
            with redirect_stdout(StringIO()) as output:
                check.assertEqual(runner.main(argv), 1)
            report = json.loads(output.getvalue())
            check.assertEqual(report["blockers"], [reason])
            check.assertFalse(fixture.args.output.exists())
        else:
            report = runner.plan_run(fixture.args, fixture.paths)
            check.assertEqual(report["outcome"], "pass", report["blockers"])
            if stage == "preflight":
                helper.write_bytes(malformed)
            else:
                fixture.after_command = lambda name, build: (
                    helper.write_bytes(malformed) if name == stage else None)
            report = runner.execute_run(fixture.args, report, fixture.paths)
            retained = json.loads((fixture.args.output / "report.json").read_text())
            check.assertEqual(retained, report)
            check.assertEqual(report["state"], "finished")
            check.assertEqual(report["reason"], reason)
            check.assertNotIn("active_command", report)
            check.assertNotIn("observations", report["cases"][0])
            expected = [] if stage == "preflight" else ["units-configure"]
            if stage == "cp-llc-port-run":
                expected.extend(("cp-llc-port-build", "cp-llc-port-run"))
            check.assertEqual([entry["id"] for entry in report["commands"]], expected)
            check.assertEqual(process.call_count, len(expected))
            check.assertEqual(report["cases"][0]["outcome"],
                              "fail" if stage == "cp-llc-port-run" else "not_run")
            if expected:
                check.assertEqual(report["commands"][-1]["outcome"], "pass")
                snapshot = next(item for item in report["snapshots"]
                                if item["source"]["path"] == helper.name)
                check.assertEqual((fixture.args.output / snapshot["retained"]["path"]).read_bytes(),
                                  original)
        blocked = stage in ("plan", "preflight")
        check.assertEqual(report["outcome"], "blocked" if blocked else "fail")
        check.assertIs(report.get("execution_performed", False), not blocked)
        check.assertIs(report.get("workload_command_started", False), stage == "cp-llc-port-run")
        for key in ("workload_execution_verified", "qualifies_P01_A03",
                    "vendor_execution_performed", "phase_complete"):
            check.assertIs(report.get(key, False), False, key)
        if blocked:
            process.assert_not_called()
            check.assertFalse(fixture.args.build_root.exists())
        oracle.assert_not_called()
    finally:
        helper.write_bytes(original)
print(json.dumps({"stage": stage, "outcome": report["outcome"], "reason": reason,
                  "workload_execution_verified": report.get("workload_execution_verified", False)}))
'''


class QualificationIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="local-qualification-identity-")
        self.addCleanup(temporary.cleanup)
        self.fixture = RunnerFixture(Path(temporary.name).resolve())
        self.enterContext(mock.patch.dict(os.environ, self.fixture.environment, clear=True))
        self.enterContext(mock.patch.object(runner, "HERE", self.fixture.helpers))
        self.enterContext(mock.patch.object(inventory, "HERE", self.fixture.helpers))
        capacity = type(shutil.disk_usage(self.fixture.base))(
            64 * runner.GIB, runner.GIB, 63 * runner.GIB)
        self.enterContext(mock.patch.object(shutil, "disk_usage", return_value=capacity))
        self.process = self.enterContext(mock.patch.object(
            runner, "run_bounded", side_effect=self.fixture.command))

    def plan(self):
        report = runner.plan_run(self.fixture.args, self.fixture.paths)
        self.assertEqual(report["outcome"], "pass", report["blockers"])
        for key in ("execution_performed", "workload_command_started", "workload_execution_verified"):
            self.assertIs(report[key], False, key)
        return report

    def execute(self, report=None):
        return runner.execute_run(self.fixture.args, self.plan() if report is None else report,
                                  self.fixture.paths)

    def assertRetained(self, report, outcome):
        self.assertEqual(report["outcome"], outcome, report.get("reason"))
        self.assertEqual(report["state"], "finished")
        retained = json.loads((self.fixture.args.output / "report.json").read_text())
        self.assertEqual(retained, report)
        self.assertTrue(report["snapshots"])
        for snapshot in report["snapshots"]:
            data = (self.fixture.args.output / snapshot["retained"]["path"]).read_bytes()
            self.assertEqual(len(data), snapshot["source"]["size_bytes"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), snapshot["source"]["sha256"])
        for key in ("qualifies_P01_A03", "vendor_execution_performed", "phase_complete"):
            self.assertIs(retained[key], False, key)

    def block_before_launch(self, command_id):
        blocked = []

        def command(argv, build, environment, log, **budget):
            if log.stem != command_id:
                return self.fixture.command(argv, build, environment, log, **budget)
            with mock.patch.object(baseline_process, "_disk_has_reserve", return_value=False):
                with mock.patch.object(baseline_process.subprocess, "Popen") as launch:
                    result = baseline_process.run_bounded(argv, build, environment, log, **budget)
                    launch.assert_not_called()
            self.assertEqual(result["outcome"], "blocked")
            self.assertEqual(result["reason"], "disk_reserve")
            self.assertIs(result["process_started"], False)
            self.assertIsNone(result["exit_code"])
            blocked.append(result)
            return result

        self.process.side_effect = command
        return blocked

    def test_helper_changed_after_real_import_blocks_planning(self):
        arguments = {key: str(value) if isinstance(value, Path) else value
                     for key, value in vars(self.fixture.args).items()}
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c", IMPORT_MUTATION_PROBE,
             str(self.fixture.helpers), json.dumps(arguments)],
            env=self.fixture.environment, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "changed_helper_rejected": True, "restored_plan": "pass", "execution_performed": False,
        })
        self.process.assert_not_called()
        self.assertFalse(self.fixture.args.output.exists())
        self.assertFalse(self.fixture.args.build_root.exists())

    def malformed_helper_probe(self, stage):
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c", MALFORMED_HELPER_PROBE,
             str(self.fixture.helpers), str(Path(__file__).resolve().parent), stage],
            env=self.fixture.environment, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "stage": stage, "outcome": "blocked" if stage in ("plan", "preflight") else "fail",
            "reason": "local helper has invalid Python syntax: local_qualification_cases.py",
            "workload_execution_verified": False,
        })
        self.process.assert_not_called()

    def test_malformed_helper_after_real_import_blocks_planning(self):
        self.malformed_helper_probe("plan")

    def test_malformed_helper_after_planning_retains_blocked_preflight(self):
        self.malformed_helper_probe("preflight")

    def test_malformed_helper_after_command_retains_failure_without_verification(self):
        for command in ("units-configure", "cp-llc-port-run"):
            with self.subTest(command=command):
                self.malformed_helper_probe(command)

    def test_prelaunch_blocked_configure_does_not_claim_execution(self):
        blocked = self.block_before_launch("units-configure")
        with mock.patch.object(runner, "verify_log", wraps=runner.verify_log) as oracle:
            report = self.execute()
        self.assertRetained(report, "fail")
        self.assertEqual(len(blocked), 1)
        self.assertEqual([entry["id"] for entry in report["commands"]], ["units-configure"])
        for key in ("execution_performed", "workload_command_started", "workload_execution_verified"):
            self.assertIs(report[key], False, key)
        self.assertEqual(report["cases"][0]["outcome"], "not_run")
        oracle.assert_not_called()

    def test_prelaunch_blocked_workload_does_not_claim_workload_execution(self):
        blocked = self.block_before_launch("cp-llc-port-run")
        with mock.patch.object(runner, "verify_log", wraps=runner.verify_log) as oracle:
            report = self.execute()
        self.assertRetained(report, "fail")
        self.assertEqual(len(blocked), 1)
        self.assertIs(report["execution_performed"], True)
        self.assertIs(report["workload_command_started"], False)
        self.assertIs(report["workload_execution_verified"], False)
        self.assertIs(report["commands"][-1]["process_started"], False)
        self.assertEqual(report["cases"][0]["outcome"], "fail")
        oracle.assert_not_called()

    def test_failed_started_workload_command_never_reaches_oracle(self):
        self.fixture.failures["cp-llc-port-run"] = {
            "outcome": "fail", "exit_code": 2, "reason": "inert rebuild failure",
        }
        with mock.patch.object(runner, "verify_log", wraps=runner.verify_log) as oracle:
            report = self.execute()
        self.assertRetained(report, "fail")
        self.assertIs(report["execution_performed"], True)
        self.assertIs(report["workload_command_started"], True)
        self.assertIs(report["workload_execution_verified"], False)
        self.assertEqual(report["cases"][0]["outcome"], "fail")
        self.assertNotIn("observations", report["cases"][0])
        oracle.assert_not_called()

    def test_oracle_failure_does_not_verify_a_successful_workload_command(self):
        self.fixture.logs["cp-llc-port"] = "PASSED\nFAILED\n"
        with mock.patch.object(runner, "verify_log", wraps=runner.verify_log) as oracle:
            report = self.execute()
        self.assertRetained(report, "fail")
        self.assertEqual(report["commands"][-1]["outcome"], "pass")
        self.assertIs(report["workload_command_started"], True)
        self.assertIs(report["workload_execution_verified"], False)
        self.assertEqual(report["cases"][0]["outcome"], "fail")
        self.assertIn("failure evidence", report["reason"])
        self.assertNotIn("observations", report["cases"][0])
        oracle.assert_called_once()

    def test_verification_is_recorded_only_after_real_oracle_passes(self):
        report = self.plan()
        verify_log = runner.verify_log

        def verify(case, text):
            retained = json.loads((self.fixture.args.output / "report.json").read_text())
            for current in (report, retained):
                self.assertIs(current["execution_performed"], True)
                self.assertIs(current["workload_command_started"], True)
                self.assertIs(current["workload_execution_verified"], False)
                self.assertEqual(current["cases"][0]["outcome"], "not_run")
            return verify_log(case, text)

        with mock.patch.object(runner, "verify_log", side_effect=verify) as oracle:
            result = self.execute(report)
        self.assertRetained(result, "pass")
        self.assertIs(result["workload_execution_verified"], True)
        self.assertEqual(result["cases"][0]["outcome"], "pass")
        self.assertEqual(result["cases"][0]["observations"]["outcome"], "pass")
        oracle.assert_called_once()


if __name__ == "__main__":
    unittest.main()
