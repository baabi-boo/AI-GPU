# SPDX-License-Identifier: Apache-2.0
"""Preparation receipt faults retain known nonstarts without provisioning."""

from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import p06_dependency_contract as contract
import p06_dependency_local_prepare as prepare
import test_p06_dependency_local_prepare as fixtures


HERE = Path(__file__).resolve().parent


def _cli_scenario(directory, boundary):
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    previous = signal.getsignal(signal.SIGTERM)
    sigint = signal.getsignal(signal.SIGINT)
    case = fixtures.LocalPreparationExecutionTests()
    try:
        case.setUp()
        target = case.workspace / "evidence/dependency-preparation.json"
        write_json = prepare.base._write_json
        writes = []

        def checkpoint(path, document):
            writes.append({name: deepcopy(document[name]) for name in ("outcome", "reason", "failures")})
            if boundary == "initial" and len(writes) == 1:
                os.kill(os.getpid(), signal.SIGTERM)
                raise AssertionError("SIGTERM did not interrupt the initial checkpoint")
            return write_json(path, document)

        def provision(*args):
            os.kill(os.getpid(), signal.SIGTERM)
            raise AssertionError("SIGTERM did not interrupt provisioning")

        case.mocks["provision"].side_effect = provision
        arguments = [item for name, value in vars(case.args).items() if value is not None
                     for item in ("--" + name.replace("_", "-"), str(value))]
        with mock.patch.object(prepare.base, "_write_json", side_effect=checkpoint):
            status = prepare.main(arguments)
        result = {"main_status": status, "report": json.loads(target.read_text()), "writes": writes,
                  "calls": {name: case.mocks[name].call_count for name in
                            ("source", "resources", "objects", "tools", "git", "provision")},
                  "tools_created": (case.workspace / "tools").exists(),
                  "handler_restored": signal.getsignal(signal.SIGTERM) is previous,
                  "sigint_unchanged": signal.getsignal(signal.SIGINT) is sigint}
        (Path(directory) / "result.json").write_text(json.dumps(result), encoding="utf-8")
        return status
    finally:
        case.doCleanups()


class PreparationInitialCloseoutTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.LocalPreparationExecutionTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()

    def assert_initial_checkpoint_closeout(self, error, reason):
        target = self.case.workspace / "evidence/dependency-preparation.json"
        write_json = prepare.base._write_json
        writes = []

        def fail_first_write(path, document):
            writes.append((path, deepcopy(document)))
            if len(writes) == 1:
                raise error
            return write_json(path, document)

        with mock.patch.object(prepare.base, "_write_json", side_effect=fail_first_write):
            try:
                result = self.case.run_prepare()
            except (OSError, KeyboardInterrupt) as escaped:
                self.fail(f"{type(escaped).__name__} escaped initial checkpoint; "
                          f"receipt_exists={target.exists()}; "
                          f"provision_calls={self.case.mocks['provision'].call_count}")

        self.assertEqual([path for path, _ in writes], [target, target])
        self.assertIsNone(writes[0][1]["reason"])
        self.assertEqual(writes[-1][1], result)
        self.assertEqual(result["outcome"], "blocked")
        self.assertEqual(result["reason"], reason)
        self.assertEqual(result["failures"], [{"stage": "local-preparation", "reason": reason}])
        self.assertEqual(result["native_execution"], "not_run")
        self.assertEqual(result["host_tools"], {})
        self.assertEqual(result["repositories"], {})
        for name in ("archive_root", "dependency_repositories_root", "host_bin", "source_manifest",
                     "toolchain_receipt", "source_before", "source_after", "resources_before", "resources_after"):
            self.assertIsNone(result[name], name)
        for name in ("dependency_cache_used", "toolchain_cache_used", "network_acquisition", *contract.FALSE_CLAIMS):
            self.assertIs(result[name], False, name)
        self.assertEqual(result["budget"], contract.BUDGET)
        for name in ("source", "resources", "objects", "tools", "git", "provision"):
            self.case.mocks[name].assert_not_called()
        self.assertEqual(self.case.calls, [])
        self.assertFalse((self.case.workspace / "tools").exists())

    def test_initial_oserror_retains_known_nonstart(self):
        self.assert_initial_checkpoint_closeout(OSError("initial receipt unavailable"),
                                               "initial receipt unavailable")

    def test_initial_interrupt_retains_known_nonstart(self):
        self.assert_initial_checkpoint_closeout(KeyboardInterrupt(), "interrupted")


class PreparationCliCancellationTests(unittest.TestCase):
    def assert_sigterm_closeout(self, boundary, outcome, writes, provision_calls):
        with tempfile.TemporaryDirectory(prefix="p06-preparation-sigterm-") as temporary:
            directory = Path(temporary).resolve()
            code = ("import sys; from test_p06_preparation_initial_closeout import _cli_scenario; "
                    "sys.exit(_cli_scenario(sys.argv[1], sys.argv[2]))")
            result = subprocess.run([sys.executable, "-B", "-c", code, str(directory), boundary],
                cwd=HERE, env=dict(os.environ, TMPDIR=str(directory), PYTHONDONTWRITEBYTECODE="1"),
                capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stderr, "")
            observed = json.loads((directory / "result.json").read_text())

        report = observed["report"]
        self.assertEqual(observed["main_status"], 1)
        self.assertEqual(report["outcome"], outcome)
        self.assertEqual(report["reason"], "interrupted")
        self.assertEqual(report["failures"], [{"stage": "local-preparation", "reason": "interrupted"}])
        self.assertEqual(json.loads(result.stdout), {name: report[name] for name in
            ("contract_id", "execution_origin", "outcome", "reason", "native_execution")})
        self.assertEqual(len(observed["writes"]), writes)
        self.assertEqual(observed["writes"][-1], {name: report[name] for name in ("outcome", "reason", "failures")})
        self.assertEqual(observed["calls"]["provision"], provision_calls)
        self.assertEqual(observed["calls"]["source"], provision_calls)
        self.assertEqual(observed["calls"]["resources"], provision_calls)
        self.assertEqual(observed["calls"]["objects"], provision_calls)
        self.assertEqual(observed["calls"]["tools"], provision_calls)
        self.assertIsNone(report["toolchain_receipt"])
        self.assertIsNone(report["source_after"])
        self.assertIsNone(report["resources_after"])
        self.assertEqual(report["native_execution"], "not_run")
        for name in ("dependency_cache_used", "toolchain_cache_used", "network_acquisition", *contract.FALSE_CLAIMS):
            self.assertIs(report[name], False, name)
        self.assertIs(observed["tools_created"], False)
        self.assertIs(observed["handler_restored"], True)
        self.assertIs(observed["sigint_unchanged"], True)

    def test_sigterm_at_initial_checkpoint_retains_blocked_nonstart(self):
        self.assert_sigterm_closeout("initial", "blocked", 2, 0)

    def test_sigterm_during_provision_retains_failed_preparation(self):
        self.assert_sigterm_closeout("provision", "fail", 3, 1)

    def test_sigterm_during_handler_installation_restores_enclosing_handler(self):
        install = signal.signal
        previous = signal.getsignal(signal.SIGTERM)
        sigint = signal.getsignal(signal.SIGINT)
        injections = []

        def enclosing(number, frame):
            raise AssertionError("enclosing handler must not run during CLI setup")

        def install_and_interrupt(number, handler):
            prior = install(number, handler)
            if not injections:
                injections.append(number)
                os.kill(os.getpid(), signal.SIGTERM)
            return prior

        install(signal.SIGTERM, enclosing)
        try:
            with mock.patch.object(prepare, "_main") as body, \
                    mock.patch.object(prepare.signal, "signal", side_effect=install_and_interrupt):
                with self.assertRaises(KeyboardInterrupt):
                    prepare.main([])
            body.assert_not_called()
            self.assertEqual(injections, [signal.SIGTERM])
            self.assertIs(signal.getsignal(signal.SIGINT), sigint)
            self.assertIs(signal.getsignal(signal.SIGTERM), enclosing)
        finally:
            install(signal.SIGTERM, previous)
            install(signal.SIGINT, sigint)


if __name__ == "__main__":
    unittest.main()
