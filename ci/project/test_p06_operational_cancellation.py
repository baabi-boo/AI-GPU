# SPDX-License-Identifier: Apache-2.0
"""Real SIGTERM at operational boundaries with inert children; no native work."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from baseline_process import run_bounded
import p06_qualified_warm_hosted as hosted
import p06_qualified_warm_inputs as inputs
import p06_qualified_warm_run as runner


HERE = Path(__file__).resolve().parent
PYTHON = sys.executable
SIGNAL_HELPER = "ci/project/xrt_signals.py"


def _arguments(args):
    return [item for name, value in vars(args).items()
            for item in ("--" + name.replace("_", "-"), str(value))]


def _between_children(directory, receipt=None):
    checkpoint = json.loads(receipt.read_text()) if receipt is not None else None
    (directory / "checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8")
    (directory / "ready").touch()
    signal.pause()
    raise AssertionError("SIGTERM did not interrupt the operational boundary")


def _probe(directory, observations, cwd, environment, log, limits, code, *arguments):
    outer = signal.getsignal(signal.SIGTERM)
    prefix = ("import os,pathlib,sys,time; "
              "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()),encoding='ascii'); ")
    result = run_bounded([PYTHON, "-I", "-B", "-c", prefix + code,
                          str(directory / "child.pid"), *map(str, arguments)],
                         cwd, environment, log, **limits)
    observations.append({"result": result,
        "outer_handler_installed": callable(outer),
        "outer_handler_restored": signal.getsignal(signal.SIGTERM) is outer})
    return result


def _input_scenario(directory, boundary):
    import test_p06_qualified_warm_inputs as fixtures

    fixtures.QualifiedWarmInputAcquisitionTests.setUpClass()
    fixture = fixtures.QualifiedWarmInputAcquisitionTests()
    observations = []
    try:
        fixture.setUp()
        receipt = fixture.args.output_dir / inputs.RECEIPT_NAME
        write = inputs.base._write_json

        def command(argv, cwd, environment, log, **limits):
            if observations:
                raise AssertionError("acquisition continued after cancellation")
            code = "pathlib.Path(sys.argv[2]).mkdir(); print('inert acquisition probe',flush=True); "
            if boundary == "bounded":
                code += "pathlib.Path(sys.argv[3]).touch(); time.sleep(30)"
            return _probe(directory, observations, cwd, environment, log, limits,
                          code, argv[-1], directory / "ready")

        def checkpoint(path, report):
            write(path, report)
            if (boundary == "between" and report["state"] == "running"
                    and report["commands"] and report["commands"][-1].get("exit_code") == 0):
                _between_children(directory, receipt)

        fixture.run_mock.side_effect = command
        with mock.patch.object(inputs.base, "_write_json", side_effect=checkpoint):
            status = inputs.main(_arguments(fixture.args))
        report = json.loads(receipt.read_text())
        return {"main_status": status, "report": report, "observations": observations,
                "log": (fixture.args.output_dir / report["commands"][0]["log"]).read_text()}
    finally:
        fixture.doCleanups()
        fixtures.QualifiedWarmInputAcquisitionTests.doClassCleanups()


def _run_scenario(directory):
    import test_p06_qualified_warm_run as fixtures

    fixture = fixtures.QualifiedWarmRunTests()
    observations = []
    try:
        fixture.setUp()
        receipt = fixture.workspace / "evidence" / runner.RECEIPT_PATH
        write = runner.base._write_json

        def command(argv, cwd, environment, log, **limits):
            if observations:
                raise AssertionError("supervision continued after cancellation")
            document = {"schema_version": 1, "contract_id": "p06-local-dependency-preparation-v1",
                "expected_revision": fixture.revision, "state": "finished", "outcome": "pass",
                "reason": None, "failures": [], "execution_origin": "local", "native_execution": "not_run",
                **dict.fromkeys(runner.qualification.FALSE_CLAIMS, False)}
            terminal = json.dumps(runner.report_terminal("preparation", document, fixture.paths))
            code = "pathlib.Path(sys.argv[2]).write_text(sys.argv[3]); print(sys.argv[4])"
            return _probe(directory, observations, cwd, environment, log, limits, code,
                          fixture.workspace / "evidence/dependency-preparation.json",
                          json.dumps(document), terminal)

        def checkpoint(path, report):
            write(path, report)
            if (report["state"] == "running" and report["stages"]
                    and report["stages"][-1].get("finished_at") is not None):
                _between_children(directory, receipt)

        with mock.patch.object(runner, "run_bounded", side_effect=command), mock.patch.object(
                runner.base, "_write_json", side_effect=checkpoint):
            status = runner.main(_arguments(fixture.args))
        return {"main_status": status, "report": json.loads(receipt.read_text()),
                "observations": observations}
    finally:
        fixture.doCleanups()


def _hosted_scenario(directory):
    import test_p06_qualified_warm_hosted as fixtures

    fixture = fixtures.HostedCompositionTests()
    observations = []
    try:
        fixture.setUp()

        def command(argv, cwd, environment, log, **limits):
            if observations:
                return fixture.command(argv, cwd, environment, log, **limits)
            fixture.calls.append({"module": "recipient-probe"})
            return _probe(directory, observations, cwd, environment, log, limits,
                          "print('inert recipient probe')")

        with mock.patch.object(hosted, "run_bounded", side_effect=command), mock.patch.object(
                hosted, "capacity_gate", side_effect=lambda *_: _between_children(directory)):
            status = hosted.main(["run", "--source-dir", str(fixture.source),
                "--expected-revision", fixtures.REVISION, "--attempt-root", str(fixture.attempt)])
        return {"main_status": status,
                "report": json.loads((fixture.attempt / "attempt-final.PRIVATE.json").read_text()),
                "observations": observations, "calls": [row["module"] for row in fixture.calls],
                "retained": json.loads((fixture.attempt / "retention/hosted-closeout.json").read_text())}
    finally:
        fixture.doCleanups()


def _subprocess_scenario(directory, scenario):
    directory = Path(directory)
    previous, sigint = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)
    if scenario.startswith("inputs-"):
        result = _input_scenario(directory, scenario.removeprefix("inputs-"))
    elif scenario == "run":
        result = _run_scenario(directory)
    else:
        result = _hosted_scenario(directory)
    result["handler_restored"] = signal.getsignal(signal.SIGTERM) is previous
    result["sigint_unchanged"] = signal.getsignal(signal.SIGINT) is sigint
    (directory / "result.json").write_text(json.dumps(result), encoding="utf-8")


@unittest.skipUnless(os.name == "posix" and Path("/proc/self/stat").exists(),
                     "operational cancellation requires Linux /proc")
class OperationalCancellationTests(unittest.TestCase):
    def interrupted(self, scenario):
        with tempfile.TemporaryDirectory(prefix="p06-operational-cancellation-") as temporary:
            directory = Path(temporary)
            code = ("import sys; from test_p06_operational_cancellation import _subprocess_scenario; "
                    "_subprocess_scenario(sys.argv[1],sys.argv[2])")
            process = subprocess.Popen([sys.executable, "-B", "-c", code, str(directory), scenario],
                cwd=HERE, env=dict(os.environ, TMPDIR=str(directory), PYTHONDONTWRITEBYTECODE="1"),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            try:
                deadline = time.monotonic() + 8
                while not (directory / "ready").exists():
                    if process.poll() is not None:
                        output = b"".join(process.communicate(timeout=1))
                        self.fail("scenario exited before readiness: " + output.decode("utf-8", "replace"))
                    self.assertLess(time.monotonic(), deadline, "cancellation readiness timeout: " + scenario)
                    time.sleep(0.01)
                child_pid = int((directory / "child.pid").read_text(encoding="ascii"))
                if scenario != "inputs-bounded":
                    self.assertFalse(Path("/proc", str(child_pid)).exists(), "completed child was not reaped")
                    checkpoint = json.loads((directory / "checkpoint.json").read_text())
                    if checkpoint is not None:
                        self.assertEqual(checkpoint["state"], "running")
                        rows = checkpoint["commands" if scenario == "inputs-between" else "stages"]
                        self.assertEqual(len(rows), 1)
                        self.assertEqual(rows[0]["exit_code"], 0)
                        self.assertTrue(rows[0]["cleanup_complete"])
                process.send_signal(signal.SIGTERM)
                output = b"".join(process.communicate(timeout=8))
                self.assertEqual(process.returncode, 0, output.decode("utf-8", "replace"))
                self.assertFalse(Path("/proc", str(child_pid)).exists(), "cancelled child was not reaped")
                result = json.loads((directory / "result.json").read_text())
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
                for stream in (process.stdout, process.stderr):
                    stream.close()
                marker = directory / "child.pid"
                if marker.exists():
                    try:
                        os.killpg(int(marker.read_text(encoding="ascii")), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        self.assertEqual(result["main_status"], 1)
        self.assertTrue(result["handler_restored"])
        self.assertTrue(result["sigint_unchanged"])
        self.assertEqual(len(result["observations"]), 1)
        observation = result["observations"][0]
        self.assertTrue(observation["outer_handler_installed"])
        self.assertTrue(observation["outer_handler_restored"])
        self.assertTrue(observation["result"]["process_started"])
        self.assertTrue(observation["result"]["cleanup_complete"])
        self.assertEqual(result["report"]["state"], "finished")
        self.assertEqual(result["report"]["outcome"], "fail")
        self.assertEqual(result["report"]["native_execution"], "not_run")
        for field in runner.qualification.FALSE_CLAIMS:
            self.assertIs(result["report"][field], False)
        return result

    def test_sigterm_after_acquisition_child_retains_finished_failure(self):
        result = self.interrupted("inputs-between")
        self.assertEqual(result["report"]["reason"], "interrupted")
        self.assertEqual([row["id"] for row in result["report"]["commands"]], ["yaml-cpp-init"])
        self.assertEqual(result["report"]["commands"][0]["exit_code"], 0)
        self.assertEqual(result["log"], "inert acquisition probe\n")

    def test_sigterm_after_preparation_retains_finished_supervision_failure(self):
        result = self.interrupted("run")
        report = result["report"]
        self.assertEqual(report["reason"], "interrupted")
        self.assertFalse(report["orchestration_passed"])
        self.assertEqual([row["id"] for row in report["stages"]], ["preparation"])
        self.assertEqual(report["stages"][0]["exit_code"], 0)
        self.assertEqual(report["stages"][0]["retention_errors"], [])
        self.assertIn("preparation", report["reports"])
        self.assertTrue(report["selected_sources_stable"])
        self.assertIn(SIGNAL_HELPER, [row["path"] for row in report["selected_sources_before"]])

    def test_sigterm_after_hosted_child_attempts_partial_closeout(self):
        result = self.interrupted("hosted")
        report = result["report"]
        self.assertEqual(result["calls"], ["recipient-probe", "p06_qualified_warm_pack",
                                          "p06_qualified_warm_encrypt"])
        self.assertIn({"stage": "execution", "error_type": "KeyboardInterrupt"}, report["failures"])
        self.assertFalse(report["orchestration_passed"])
        self.assertFalse(report["qualified_warm_passed"])
        self.assertTrue(report["writers_finished_observed"])
        self.assertTrue(report["packaging_passed"])
        self.assertTrue(report["encryption_passed"])
        self.assertEqual(result["retained"]["native_execution"], "not_run")
        self.assertTrue(report["selected_sources_stable"])
        self.assertIn(SIGNAL_HELPER, [row["path"] for row in report["selected_sources_before"]])

    def test_sigterm_inside_bounded_child_preserves_monitor_cleanup(self):
        result = self.interrupted("inputs-bounded")
        command = result["report"]["commands"][0]
        self.assertEqual(command["reason"], "interrupted_signal_" + str(signal.SIGTERM))
        self.assertNotEqual(command["exit_code"], 0)
        self.assertTrue(command["cleanup_complete"])
        self.assertEqual(len(result["report"]["commands"]), 1)


if __name__ == "__main__":
    unittest.main()
