# SPDX-License-Identifier: Apache-2.0
"""Offline trust, privacy and failure-closeout tests; no native GPU execution."""

from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest import mock

import p06_qualified_warm_hosted as hosted
from test_p05_ci_workflow import children, scalars, script, steps as workflow_steps, workflow as parse_workflow


REVISION = "a" * 40
RECIPIENT = "public-recipient-fixture"
SECRET = "https://private.invalid/control.zip?credential=DO-NOT-PRINT"


def context():
    return {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/master",
            "GITHUB_REPOSITORY": hosted.REPOSITORY, "GITHUB_SHA": REVISION,
            "GITHUB_WORKFLOW_SHA": REVISION,
            "GITHUB_WORKFLOW_REF": hosted.REPOSITORY + "/" + hosted.WORKFLOW + "@refs/heads/master",
            "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_TOKEN": "token_fixture",
            "P06_CONTROL_ARCHIVE_URL": SECRET, "P06_EVIDENCE_AGE_RECIPIENT": RECIPIENT,
            "P06_HOST_SETUP_READY": "true"}


def governance():
    run = {"id": 123, "run_attempt": 2, "workflow_id": 42, "path": hosted.GOVERNANCE_WORKFLOW,
           "head_sha": REVISION, "head_branch": "master", "event": "push", "status": "completed",
           "conclusion": "success", "repository": {"full_name": hosted.REPOSITORY},
           "head_repository": {"full_name": hosted.REPOSITORY}}
    job = {"id": 456, "run_id": 123, "name": "governance", "head_sha": REVISION,
           "run_attempt": 2, "status": "completed",
           "conclusion": "success", "steps": [{"name": name, "status": "completed", "conclusion": "success"}
                                               for name in hosted.GOVERNANCE_STEPS]}
    return [
        {"id": 42, "path": hosted.GOVERNANCE_WORKFLOW, "state": "active"},
        {"workflow_runs": [run]}, {"total_count": 1, "jobs": [job]}, deepcopy(run),
    ]


class HostedTrustTests(unittest.TestCase):
    def test_trusted_context_requires_exact_published_master_workflow(self):
        result = hosted.trusted_context(context(), REVISION)
        self.assertNotIn("GITHUB_TOKEN", result)
        self.assertNotIn("P06_CONTROL_ARCHIVE_URL", result)
        substitutions = {"GITHUB_EVENT_NAME": "pull_request_target", "GITHUB_REF": "refs/heads/topic",
                         "GITHUB_REPOSITORY": "fork/AI-GPU", "GITHUB_SHA": "b" * 40,
                         "GITHUB_WORKFLOW_SHA": "b" * 40, "GITHUB_WORKFLOW_REF": "other",
                         "GITHUB_RUN_ID": "1\nsecret", "GITHUB_RUN_ATTEMPT": "0"}
        for key, value in substitutions.items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                hosted.trusted_context(dict(context(), **{key: value}), REVISION)
        for revision in ("master", "a" * 39, "A" * 40, "a" * 40 + "\n"):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                hosted.trusted_context(context(), revision)

    def test_governance_requires_current_attempt_full_job_success(self):
        api = mock.Mock(side_effect=governance())
        result = hosted.verify_governance(REVISION, "fixture_token", api)
        self.assertTrue(result["provider_observed_success"])
        self.assertFalse(result["independent_packet_replay"])
        paths = [call.args[0] for call in api.call_args_list]
        self.assertIn("head_sha=" + REVISION, paths[1])
        self.assertIn("/attempts/2/jobs?per_page=100", paths[2])
        self.assertTrue(paths[3].endswith("/runs/123"))
        self.assertEqual(result["required_steps"], list(hosted.GOVERNANCE_STEPS))

    def test_wrong_revision_branch_origin_event_and_conclusion_do_not_admit(self):
        changes = {"head_sha": "b" * 40, "head_branch": "topic", "event": "pull_request",
                   "path": ".github/workflows/lookalike.yml", "conclusion": "failure",
                   "status": "in_progress", "workflow_id": 43,
                   "head_repository": {"full_name": "fork/AI-GPU"},
                   "repository": {"full_name": "fork/AI-GPU"}, "run_attempt": True}
        for key, value in changes.items():
            with self.subTest(key=key):
                fixtures = governance()
                fixtures[1]["workflow_runs"][0][key] = value
                with self.assertRaises(ValueError):
                    hosted.verify_governance(REVISION, "fixture_token", mock.Mock(side_effect=fixtures))

    def test_skipped_missing_duplicate_or_failed_full_runner_step_is_rejected(self):
        for change in ("skipped", "failure", "missing", "duplicate"):
            with self.subTest(change=change):
                fixtures = governance()
                steps = fixtures[2]["jobs"][0]["steps"]
                selected = next(row for row in steps if row["name"] == "Test governance tooling")
                if change == "missing":
                    steps.remove(selected)
                elif change == "duplicate":
                    steps.append(dict(selected))
                else:
                    selected["conclusion"] = change
                with self.assertRaises(ValueError):
                    hosted.verify_governance(REVISION, "fixture_token", mock.Mock(side_effect=fixtures))

    def test_governance_observation_cannot_span_changed_attempts(self):
        for key, value in (("run_attempt", 3), ("id", 124)):
            with self.subTest(key=key):
                fixtures = governance()
                fixtures[3][key] = value
                with self.assertRaises(ValueError):
                    hosted.verify_governance(REVISION, "fixture_token", mock.Mock(side_effect=fixtures))

    def test_governance_api_failures_and_oversized_populations_fail_closed(self):
        fixtures = governance()
        fixtures[1]["workflow_runs"] *= 101
        with self.assertRaises(ValueError):
            hosted.verify_governance(REVISION, "fixture_token", mock.Mock(side_effect=fixtures))
        for token in (None, "", "token\r\nInjected: secret", "x" * 257):
            api = mock.Mock()
            with self.subTest(token=token), self.assertRaises(ValueError):
                hosted.verify_governance(REVISION, token, api)
            api.assert_not_called()
        with self.assertRaises(OSError):
            hosted.verify_governance(REVISION, "fixture_token", mock.Mock(side_effect=OSError("private error")))

    def test_governance_tls_does_not_enable_ambient_session_key_logging(self):
        response = mock.MagicMock(status=200)
        response.read.return_value = b"{}"
        opener = mock.Mock()
        opener.open.return_value.__enter__ = mock.Mock(return_value=response)
        opener.open.return_value.__exit__ = mock.Mock(return_value=False)
        with tempfile.TemporaryDirectory() as directory:
            keylog = Path(directory) / "session-keys.log"
            with mock.patch.dict(os.environ, {"SSLKEYLOGFILE": str(keylog)}), \
                    mock.patch.object(hosted.governance_api, "build_opener", return_value=opener) as factory:
                self.assertEqual(hosted.governance_api._network_bytes(
                    "/repos/" + hosted.REPOSITORY + "/actions/runs", "fixture_token"), b"{}")
                handler = next(arg for arg in factory.call_args.args
                               if isinstance(arg, hosted.governance_api.HTTPSHandler))
                self.assertIsNone(handler._context.keylog_filename)
                self.assertEqual(handler._context.verify_mode, ssl.CERT_REQUIRED)
                self.assertTrue(handler._context.check_hostname)
                self.assertGreater(handler._context.cert_store_stats()["x509_ca"], 0)
                self.assertEqual(handler._debuglevel, 0)
                self.assertEqual(os.environ["SSLKEYLOGFILE"], str(keylog))
            self.assertFalse(keylog.exists())

    def test_governance_http_debug_cannot_print_authorization(self):
        class Socket:
            def makefile(self, _mode):
                return io.BytesIO(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")

            def sendall(self, _body):
                pass

            def close(self):
                pass

        def connect(connection):
            connection.sock = Socket()

        with mock.patch.object(http.client.HTTPConnection, "debuglevel", 1), \
                mock.patch.object(http.client.HTTPSConnection, "connect", new=connect), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertEqual(hosted.governance_api._network_bytes(
                "/repos/" + hosted.REPOSITORY + "/actions/runs", "fixture_token"), b"{}")
            self.assertEqual(stdout.getvalue() + stderr.getvalue(), "")

    def test_source_requires_clean_exact_eight_recursive_gitlinks(self):
        rows = [{"path": name, "revision": "b" * 40, "status": "initialized"}
                for name in hosted.RECURSIVE_SUBMODULES]
        source = {"revision": REVISION, "dirty": False, "blockers": [], "submodules": {"entries": rows}}
        with mock.patch.object(hosted, "collect_source", return_value=source), mock.patch.object(hosted, "_git", return_value=b""):
            self.assertEqual(hosted.verify_source(hosted.ROOT, REVISION), source)
            for mutation in ("missing", "dirty", "mismatch"):
                with self.subTest(mutation=mutation):
                    damaged = deepcopy(source)
                    if mutation == "missing":
                        damaged["submodules"]["entries"].pop()
                    elif mutation == "dirty":
                        damaged["dirty"] = True
                    else:
                        damaged["submodules"]["entries"][0]["status"] = "revision_mismatch"
                    with mock.patch.object(hosted, "collect_source", return_value=damaged), self.assertRaises(ValueError):
                        hosted.verify_source(hosted.ROOT, REVISION)
            with mock.patch.object(hosted, "_git", return_value=b"!! ignored-input\n"), self.assertRaises(ValueError):
                hosted.verify_source(hosted.ROOT, REVISION)

    def test_capacity_known_shortfall_or_incomplete_observation_blocks(self):
        observed = {"known_memory_shortfall": False, "observation_complete": True,
                    "effective_capacity_status": "unknown", "host_available_bytes": 8 * 1024**3}
        with mock.patch.object(hosted.shutil, "disk_usage", return_value=mock.Mock(free=20 * 1024**3)):
            with mock.patch.object(hosted.capacity, "observe_capacity", return_value=observed):
                result = hosted.capacity_gate(Path("/source"), Path("/attempt"))
                self.assertTrue(result["gate_satisfied"])
                self.assertFalse(result["effective_capacity_established"])
            for key, value in (("known_memory_shortfall", True), ("known_memory_shortfall", None),
                               ("observation_complete", False), ("effective_capacity_status", "unlimited"),
                               ("host_available_bytes", 1)):
                with self.subTest(key=key, value=value), mock.patch.object(
                        hosted.capacity, "observe_capacity", return_value=dict(observed, **{key: value})):
                    self.assertFalse(hosted.capacity_gate(Path("/source"), Path("/attempt"))["gate_satisfied"])
            with mock.patch.object(hosted.capacity, "observe_capacity", return_value=observed), mock.patch.object(
                    hosted.shutil, "disk_usage", return_value=mock.Mock(free=15 * 1024**3 - 1)):
                self.assertFalse(hosted.capacity_gate(Path("/source"), Path("/attempt"))["gate_satisfied"])


class HostedCompositionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "source"
        self.source.mkdir()
        for name in hosted.SOURCE_FILES:
            target = self.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(("inert selected helper fixture: " + name).encode())
        self.attempt = self.root / "attempt"
        self.diagnostic = self.source / hosted.DIAGNOSTIC
        self.diagnostic.parent.mkdir(parents=True, exist_ok=True)
        self.diagnostic.write_bytes(b"opaque original diagnostic fixture")
        self.pin = {"size_bytes": self.diagnostic.stat().st_size,
                    "sha256": hashlib.sha256(self.diagnostic.read_bytes()).hexdigest()}
        self.calls, self.failures = [], set()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.dict(os.environ, context(), clear=True))
        self.stack.enter_context(mock.patch.dict(hosted.runner.ORIGINAL_ARCHIVES, {"diagnostic_archive": self.pin}))
        self.stack.enter_context(mock.patch.object(hosted, "preflight", return_value={"fixture_only": True}))
        self.stack.enter_context(mock.patch.object(hosted.encryption, "validate_recipient", return_value=RECIPIENT))
        self.stack.enter_context(mock.patch.object(hosted.sys, "version_info", (3, 12, 14)))
        self.stack.enter_context(mock.patch.object(hosted.sys, "executable", "/fixture/python/bin/python3"))
        self.stack.enter_context(mock.patch.object(hosted.platform, "machine", return_value="x86_64"))
        self.stack.enter_context(mock.patch.object(hosted.platform, "python_implementation", return_value="CPython"))
        self.stack.enter_context(mock.patch.object(hosted, "provision_age", side_effect=self.age))
        self.stack.enter_context(mock.patch.object(hosted, "provision_host", side_effect=self.host))
        self.stack.enter_context(mock.patch.object(hosted, "capacity_gate", return_value={"gate_satisfied": True}))
        self.stack.enter_context(mock.patch.object(hosted, "run_bounded", side_effect=self.command))

    def age(self, attempt, _stage):
        target = attempt / "bootstrap/age"
        target.write_bytes(b"inert fixture, never executed")
        return target

    def host(self, attempt, _stage):
        target = attempt / "host-bin"
        target.mkdir()
        return target

    def write(self, path, document):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), encoding="utf-8")

    def command(self, argv, cwd, environment, log, **budget):
        module = Path(argv[2]).stem if len(argv) > 2 and argv[1] == "-B" else "recipient-probe"
        self.calls.append({"module": module, "argv": list(argv), "environment": dict(environment), "budget": budget})
        log.write_bytes(b"private command output: " + SECRET.encode() + b"\n")
        failed = module in self.failures
        if module == "p06_qualified_warm_control":
            self.write(self.attempt / "control/control-intake.json",
                       {"outcome": "fail" if failed else "pass", "original_verified": not failed})
            (self.attempt / "control/control-original.zip").write_bytes(b"private vendor fixture")
        elif module == "p06_qualified_warm_inputs":
            self.write(self.attempt / "acquisition/input-acquisition.json", {
                "state": "finished", "outcome": "fail" if failed else "pass", "expected_revision": REVISION,
                "commands": [{"process_started": True, "cleanup_complete": True}]})
        elif module == "p06_qualified_warm_run":
            self.write(self.attempt / "workspace/evidence/qualified-warm-run.json", {
                "state": "finished", "expected_revision": REVISION, "orchestration_passed": not failed,
                "native_execution": "run", "completed_counts": dict(hosted.runner.COMPLETE_COUNTS), "stages": []})
        elif module == "p06_qualified_warm_pack":
            packet = self.attempt / "retention/packet"
            packet.mkdir()
            (packet / ("incomplete-private.zip" if failed else "private.zip")).write_bytes(b"private fixture")
        elif module == "p06_qualified_warm_encrypt":
            public = self.attempt / "public"
            public.mkdir()
            paths = list((self.attempt / "retention").rglob("*"))
            files = [path for path in paths if path.is_file()]
            input_bytes = sum(path.stat().st_size for path in files)
            cipher = b"opaque ciphertext fixture\n" * (input_bytes // 25 + 512)
            (public / "qualified-warm-retention.tar.age").write_bytes(cipher)
            summary = {"schema_version": 1, "contract_id": hosted.encryption.CONTRACT_ID,
                       "expected_revision": REVISION, "outcome": "pass", "encryption_passed": True,
                       "file_count": len(files), "directory_count": 1 + sum(path.is_dir() for path in paths),
                       "input_bytes": input_bytes, "ciphertext_bytes": len(cipher),
                       "ciphertext_sha256": hashlib.sha256(cipher).hexdigest()}
            self.write(public / "encryption-summary.json", summary)
            self.write(log, summary)
        return {"process_started": True, "cleanup_complete": True, "exit_code": 1 if failed else 0,
                "outcome": "fail" if failed else "pass", "reason": "failed" if failed else None}

    def execute(self):
        output = io.StringIO()
        with redirect_stdout(output):
            result = hosted.execute(self.source, REVISION, self.attempt)
        self.assertNotIn(SECRET, output.getvalue())
        self.assertNotIn(str(self.attempt), output.getvalue())
        self.assertNotIn("token_fixture", output.getvalue())
        for line in output.getvalue().splitlines():
            self.assertEqual(set(json.loads(line)), {"contract_id", "expected_revision", "stage", "outcome"})
        return result

    def test_success_composes_exact_flags_with_private_env_and_unchanged_budgets(self):
        result = self.execute()
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual([call["module"] for call in self.calls], ["recipient-probe", "p06_qualified_warm_control",
                         "p06_qualified_warm_inputs", "p06_qualified_warm_run", "p06_qualified_warm_pack",
                         "p06_qualified_warm_encrypt"])
        native = next(row for row in self.calls if row["module"] == "p06_qualified_warm_run")
        self.assertEqual(native["budget"]["timeout_seconds"], 5520)
        self.assertEqual(native["budget"]["min_free_bytes"], 15 * 1024**3)
        self.assertEqual(native["budget"]["max_rss_bytes"], 4 * 1024**3)
        self.assertEqual(native["budget"]["max_log_bytes"], 16 * 1024**2)
        self.assertEqual({arg for arg in native["argv"] if arg.startswith("--")}, {
            "--source-dir", "--workspace-dir", "--expected-revision", "--archive-root",
            "--dependency-repositories", "--diagnostic-archive", "--control-archive", "--host-bin"})
        for call in self.calls:
            self.assertNotIn(SECRET, " ".join(call["argv"]))
            self.assertNotIn("GITHUB_TOKEN", call["environment"])
            self.assertEqual("P06_CONTROL_ARCHIVE_URL" in call["environment"],
                             call["module"] == "p06_qualified_warm_control")
        packed = next(row for row in self.calls if row["module"] == "p06_qualified_warm_pack")
        self.assertIn("success", packed["argv"])
        self.assertIn("--writers-finished", packed["argv"])
        for name in hosted.dependency.FALSE_CLAIMS:
            self.assertIs(result[name], False)
        self.assertIs(result["qualified_warm_passed"], False)
        self.assertEqual((self.attempt / "hosted/logs/control-intake.log").stat().st_mode & 0o777, 0o600)

    def test_operational_sources_are_bounded_private_and_checked_after_execution(self):
        result = self.execute()
        self.assertTrue(result["selected_sources_stable"])
        self.assertEqual(result["selected_sources_before"], result["selected_sources_after"])
        retained = self.attempt / result["retained_sources_root"]
        self.assertEqual(hosted.selected_sources(retained), hosted.selected_sources(self.source))
        required = {hosted.WORKFLOW, hosted.GOVERNANCE_WORKFLOW,
                    *("ci/project/p06_qualified_warm_" + name + ".py"
                      for name in ("hosted", "control", "capacity", "pack", "encrypt")),
                    "ci/project/p06_governance_artifact.py",
                    *("ci/project/governance_replay" + name + ".py"
                      for name in ("", "_archive", "_events", "_records", "_source", "_collect"))}
        self.assertTrue(required <= {row["path"] for row in result["selected_sources_before"]})
        self.assertLessEqual(len(result["selected_sources_before"]), hosted.runner.MAX_SOURCE_FILES)
        self.assertTrue(all((retained / row["path"]).stat().st_mode & 0o777 == 0o600
                            for row in result["selected_sources_before"]))

    def test_changed_operational_source_blocks_further_execution_and_delivery(self):
        def changed(argv, *args, **kwargs):
            result = self.command(argv, *args, **kwargs)
            if len(argv) > 2 and Path(argv[2]).stem == "p06_qualified_warm_inputs":
                (self.source / "ci/project/p06_qualified_warm_encrypt.py").write_bytes(b"changed fixture")
            return result

        with mock.patch.object(hosted, "run_bounded", side_effect=changed):
            result = self.execute()
        self.assertEqual(result["outcome"], "fail")
        self.assertFalse(result["selected_sources_stable"])
        self.assertFalse(result["encryption_passed"])
        self.assertNotIn("p06_qualified_warm_run", [row["module"] for row in self.calls])

    def test_zero_exit_with_inconsistent_encryption_receipt_cannot_pass(self):
        def damaged(argv, *args, **kwargs):
            result = self.command(argv, *args, **kwargs)
            if len(argv) > 2 and Path(argv[2]).stem == "p06_qualified_warm_encrypt":
                path = self.attempt / "public/encryption-summary.json"
                summary = json.loads(path.read_text())
                summary["expected_revision"] = "b" * 40
                self.write(path, summary)
            return result

        with mock.patch.object(hosted, "run_bounded", side_effect=damaged):
            result = self.execute()
        self.assertTrue(result["orchestration_passed"])
        self.assertFalse(result["encryption_passed"])
        self.assertEqual(result["outcome"], "fail")

    def test_original_diagnostic_is_copied_to_external_single_link_inode(self):
        self.execute()
        copied = self.attempt / "originals/diagnostic-original.zip"
        self.assertEqual(copied.read_bytes(), self.diagnostic.read_bytes())
        self.assertEqual(copied.stat().st_nlink, 1)
        self.assertNotEqual((copied.stat().st_dev, copied.stat().st_ino),
                            (self.diagnostic.stat().st_dev, self.diagnostic.stat().st_ino))

    def test_configuration_gate_precedes_every_acquisition(self):
        os.environ.pop("P06_CONTROL_ARCHIVE_URL")
        result = self.execute()
        self.assertEqual(result["outcome"], "fail")
        modules = [row["module"] for row in self.calls]
        self.assertEqual(modules, ["p06_qualified_warm_pack", "p06_qualified_warm_encrypt"])
        self.assertIn("partial", self.calls[0]["argv"])

    def test_failed_host_provisioning_still_packs_and_encrypts_without_false_pass(self):
        with mock.patch.object(hosted, "provision_host", side_effect=ValueError(SECRET)):
            result = self.execute()
        self.assertEqual(result["outcome"], "fail")
        self.assertTrue(result["packaging_passed"])
        self.assertTrue(result["encryption_passed"])
        self.assertFalse(any(row["module"] == "p06_qualified_warm_run" for row in self.calls))

    def test_failed_control_intake_retains_partial_and_never_starts_native(self):
        self.failures.add("p06_qualified_warm_control")
        result = self.execute()
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual([row["module"] for row in self.calls][-2:],
                         ["p06_qualified_warm_pack", "p06_qualified_warm_encrypt"])
        self.assertFalse(any(row["module"] in ("p06_qualified_warm_inputs", "p06_qualified_warm_run") for row in self.calls))

    def test_finished_failed_native_attempt_is_partial_and_remains_failed(self):
        self.failures.add("p06_qualified_warm_run")
        result = self.execute()
        self.assertEqual(result["outcome"], "fail")
        self.assertTrue(result["encryption_passed"])
        packed = next(row for row in self.calls if row["module"] == "p06_qualified_warm_pack")
        self.assertIn("partial", packed["argv"])

    def test_failed_packaging_bytes_are_still_selected_for_encryption(self):
        self.failures.add("p06_qualified_warm_pack")
        result = self.execute()
        self.assertEqual(result["outcome"], "fail")
        self.assertFalse(result["packaging_passed"])
        self.assertTrue(result["encryption_passed"])
        self.assertTrue((self.attempt / "retention/packet/incomplete-private.zip").is_file())
        encrypted = next(row for row in self.calls if row["module"] == "p06_qualified_warm_encrypt")
        self.assertEqual(encrypted["argv"][encrypted["argv"].index("--input-dir") + 1], str(self.attempt / "retention"))

    def test_failed_encryption_cannot_turn_successful_native_attempt_green(self):
        self.failures.add("p06_qualified_warm_encrypt")
        result = self.execute()
        self.assertTrue(result["orchestration_passed"])
        self.assertTrue(result["packaging_passed"])
        self.assertFalse(result["encryption_passed"])
        self.assertEqual(result["outcome"], "fail")

    def test_unresolved_writers_do_not_receive_writers_finished_assertion(self):
        with mock.patch.object(hosted, "writers_finished", return_value=False):
            result = self.execute()
        self.assertEqual(result["outcome"], "fail")
        self.assertFalse(result["packaging_passed"])
        self.assertFalse(result["encryption_passed"])
        self.assertFalse(any(row["module"] in ("p06_qualified_warm_pack", "p06_qualified_warm_encrypt") for row in self.calls))

    def test_monitor_exception_leaves_launch_unknown_and_blocks_closeout(self):
        for module, stage, native_execution in (
                ("p06_qualified_warm_inputs", "input-acquisition", "not_run"),
                ("p06_qualified_warm_run", "native-supervisor", "unknown")):
            with self.subTest(stage=stage):
                self.attempt = self.root / ("attempt-" + stage)
                self.calls.clear()

                def interrupted(argv, cwd, environment, log, **budget):
                    result = self.command(argv, cwd, environment, log, **budget)
                    if Path(argv[2]).stem == module:
                        raise RuntimeError("monitor observation lost after launch")
                    return result

                with mock.patch.dict(os.environ, context(), clear=True), \
                        mock.patch.object(hosted, "run_bounded", side_effect=interrupted):
                    result = self.execute()
                active = next(row for row in result["stages"] if row["id"] == stage)
                self.assertIsNone(active["process_started"])
                self.assertFalse(active["cleanup_complete"])
                self.assertFalse(result["writers_finished_observed"])
                self.assertFalse(result["packaging_passed"])
                self.assertFalse(result["encryption_passed"])
                self.assertEqual(result["native_execution"], native_execution)
                self.assertEqual(result["outcome"], "fail")
                self.assertFalse(any(row["module"] in ("p06_qualified_warm_pack", "p06_qualified_warm_encrypt")
                                     for row in self.calls))

    def test_observed_prelaunch_block_allows_private_failure_closeout(self):
        def blocked(argv, cwd, environment, log, **budget):
            if len(argv) > 2 and Path(argv[2]).stem == "p06_qualified_warm_inputs":
                return {"process_started": False, "cleanup_complete": True, "exit_code": None,
                        "outcome": "blocked", "reason": "disk_reserve"}
            return self.command(argv, cwd, environment, log, **budget)

        with mock.patch.object(hosted, "run_bounded", side_effect=blocked):
            result = self.execute()
        active = next(row for row in result["stages"] if row["id"] == "input-acquisition")
        self.assertIs(active["process_started"], False)
        self.assertTrue(active["cleanup_complete"])
        self.assertTrue(result["writers_finished_observed"])
        self.assertTrue(result["packaging_passed"])
        self.assertTrue(result["encryption_passed"])
        self.assertEqual(result["outcome"], "fail")

    def test_missing_unfinished_and_failed_cleanup_receipts_fail_writer_observation(self):
        self.attempt.mkdir()
        stages = [{"id": "native-supervisor", "process_started": True, "cleanup_complete": True}]
        self.assertFalse(hosted.writers_finished(self.attempt, stages))
        path = self.attempt / "workspace/evidence/qualified-warm-run.json"
        for report in ({"state": "running", "stages": []},
                       {"state": "finished", "stages": [{"process_started": True, "cleanup_complete": False}]}):
            self.write(path, report)
            self.assertFalse(hosted.writers_finished(self.attempt, stages))
        self.write(path, {"state": "finished", "stages": []})
        self.assertTrue(hosted.writers_finished(self.attempt, stages))

    def test_malformed_nested_cleanup_records_fail_closed_without_aborting_closeout(self):
        self.attempt.mkdir()
        stages = [{"id": "native-supervisor", "process_started": True, "cleanup_complete": True}]
        path = self.attempt / "workspace/evidence/qualified-warm-run.json"
        self.write(path, {"state": "finished", "stages": [{"id": "dependency-build", "process_started": True,
            "cleanup_complete": True, "report_path": "dependency-build/report.json"}]})
        child = self.attempt / "workspace/evidence/dependency-build/report.json"
        for commands in ("malformed", {}, ["malformed"], [None], [{}],
                         [{"process_started": True, "cleanup_complete": False}]):
            with self.subTest(commands=commands):
                self.write(child, {"state": "finished", "commands": commands})
                self.assertFalse(hosted.writers_finished(self.attempt, stages))

    def test_existing_attempt_is_never_resumed_or_overwritten(self):
        self.attempt.mkdir()
        sentinel = self.attempt / "keep"
        sentinel.write_bytes(b"original")
        with self.assertRaises(ValueError):
            hosted.execute(self.source, REVISION, self.attempt)
        self.assertEqual(sentinel.read_bytes(), b"original")
        self.assertEqual(self.calls, [])

    def test_cli_errors_and_exceptions_emit_only_fixed_status(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(hosted.main(["--unexpected", SECRET]), 1)
        self.assertNotIn(SECRET, output.getvalue())
        output = io.StringIO()
        with redirect_stdout(output), mock.patch.object(hosted, "preflight", side_effect=ValueError(SECRET)):
            self.assertEqual(hosted.main(["preflight", "--source-dir", str(self.source), "--expected-revision", REVISION]), 1)
        self.assertNotIn(SECRET, output.getvalue())
        self.assertNotIn(str(self.source), output.getvalue())

    def test_cli_delivery_output_is_independent_of_native_outcome_and_requires_valid_encryption(self):
        output = self.root / "github-output"
        for outcome, encrypted, expected in (("pass", True, 0), ("fail", True, 1), ("fail", False, 1)):
            with self.subTest(outcome=outcome, encrypted=encrypted):
                output.write_text("")
                with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}), \
                        mock.patch.object(hosted, "execute", return_value={"outcome": outcome,
                                                                          "encryption_passed": encrypted}), \
                        redirect_stdout(io.StringIO()):
                    self.assertEqual(hosted.main(["run", "--source-dir", str(self.source),
                        "--expected-revision", REVISION, "--attempt-root", str(self.attempt)]), expected)
                self.assertEqual(output.read_text(), "encrypted_retention_ready=true\n" if encrypted else "")


class HostedEncryptionOutputTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.attempt = Path(self.directory.name)
        retention = self.attempt / "retention"
        retention.mkdir()
        (retention / ".hidden-private").write_bytes(b"private")
        (retention / "empty").mkdir()
        self.public = self.attempt / "public"
        self.public.mkdir()
        self.ciphertext = self.public / hosted.encryption.CIPHERTEXT_NAME
        self.ciphertext.write_bytes(b"inert ciphertext fixture\n" * 100)
        self.summary = {"schema_version": 1, "contract_id": hosted.encryption.CONTRACT_ID,
                        "expected_revision": REVISION, "outcome": "pass", "encryption_passed": True,
                        "file_count": 1, "directory_count": 2, "input_bytes": 7,
                        "ciphertext_bytes": self.ciphertext.stat().st_size,
                        "ciphertext_sha256": hashlib.sha256(self.ciphertext.read_bytes()).hexdigest()}
        self.publish(self.summary)

    def publish(self, summary):
        for path in (self.public / hosted.encryption.SUMMARY_NAME,
                     self.attempt / "encryption-invocation.PRIVATE.log"):
            path.write_text(json.dumps(summary), encoding="utf-8")

    def test_public_contract_counts_types_and_identity_are_reconciled(self):
        self.assertEqual(hosted.verify_encryption_output(self.attempt, REVISION), self.summary)
        changes = {"schema_version": True, "contract_id": "other", "expected_revision": "b" * 40,
                   "outcome": "fail", "encryption_passed": False, "file_count": True,
                   "directory_count": 1, "input_bytes": 8, "ciphertext_bytes": True,
                   "ciphertext_sha256": "0" * 64, "private_detail": SECRET}
        for key, value in changes.items():
            with self.subTest(key=key):
                self.publish(dict(self.summary, **{key: value}))
                with self.assertRaises(ValueError):
                    hosted.verify_encryption_output(self.attempt, REVISION)

    def test_ciphertext_and_terminal_substitutions_are_rejected(self):
        self.ciphertext.write_bytes(b"X" * self.summary["ciphertext_bytes"])
        with self.assertRaises(ValueError):
            hosted.verify_encryption_output(self.attempt, REVISION)
        self.ciphertext.write_bytes(b"inert ciphertext fixture\n" * 100)
        terminal = self.attempt / "encryption-invocation.PRIVATE.log"
        terminal.write_text(json.dumps(dict(self.summary, file_count=2)), encoding="utf-8")
        with self.assertRaises(ValueError):
            hosted.verify_encryption_output(self.attempt, REVISION)

    def test_public_extra_files_and_linked_outputs_cannot_authorize_upload(self):
        extra = self.public / "private.log"
        extra.write_text(SECRET)
        with self.assertRaises(ValueError):
            hosted.verify_encryption_output(self.attempt, REVISION)
        extra.unlink()
        original = self.attempt / "outside-ciphertext"
        self.ciphertext.rename(original)
        self.ciphertext.symlink_to(original)
        with self.assertRaises(ValueError):
            hosted.verify_encryption_output(self.attempt, REVISION)


class HostedWorkflowTests(unittest.TestCase):
    def checked_steps(self, job):
        steps = workflow_steps(job)
        for step in steps:
            for name in ("id", "uses"):
                if name in step:
                    self.assertEqual(step[name][1], [], name)
            if "run" in step:
                self.assertEqual(step["run"][0], "|")
                self.assertTrue(all(line.startswith("          ") for line in step["run"][1]))
        return steps

    def test_manual_trusted_exact_revision_read_only_workflow(self):
        workflow = parse_workflow(hosted.ROOT / hosted.WORKFLOW)
        events = children(workflow, "on", 2)
        self.assertEqual(set(events), {"workflow_dispatch"})
        self.assertEqual(events["workflow_dispatch"], ("", []))
        self.assertEqual(scalars(children(workflow, "permissions", 2)),
                         {"contents": "read", "actions": "read"})
        job = children(children(workflow, "jobs", 2), "qualified-warm", 4)
        self.assertEqual(job["if"][0], ">-")
        condition = " ".join(line.strip() for line in job["if"][1])
        for predicate in ("github.event_name == 'workflow_dispatch'", "github.repository == 'baabi-boo/AI-GPU'",
                          "github.ref == 'refs/heads/master'"):
            self.assertIn(predicate, condition)
        self.assertEqual(job["timeout-minutes"], ("180", []))
        self.assertEqual(scalars(children(workflow, "concurrency", 2))["cancel-in-progress"], "false")
        steps = self.checked_steps(job)
        configuration = children(steps[0], "env", 10)
        self.assertIn("P06_CONTROL_ARCHIVE_URL", configuration)
        self.assertIn("P06_EVIDENCE_AGE_RECIPIENT", configuration)
        checkout = next(row for row in steps if row.get("id", (None,))[0] == "checkout")
        checkout_options = scalars(children(checkout, "with", 10))
        self.assertEqual(checkout_options["ref"], "${{ github.sha }}")
        self.assertEqual(checkout_options["submodules"], "recursive")
        self.assertEqual(checkout_options["persist-credentials"], "false")
        composition = next(row for row in steps if row.get("id", (None,))[0] == "hosted")
        self.assertEqual(composition["if"],
                         ("${{ always() && !cancelled() && steps.checkout.outcome == 'success' }}", []))
        self.assertEqual(scalars(children(composition, "env", 10))["P06_HOST_SETUP_READY"],
                         "${{ steps.preflight.outcome == 'success' && steps.python.outcome == 'success' }}")
        for step in steps:
            if "uses" in step:
                self.assertRegex(step["uses"][0].split(" #", 1)[0], r"^actions/[a-z-]+@[0-9a-f]{40}$")
        self.assertFalse(any("governance_run.py" in script(row) for row in steps if "run" in row))

    def test_artifact_upload_has_only_ciphertext_and_sanitized_summary(self):
        workflow = parse_workflow(hosted.ROOT / hosted.WORKFLOW)
        job = children(children(workflow, "jobs", 2), "qualified-warm", 4)
        steps = self.checked_steps(job)
        upload = next(row for row in steps
                      if row.get("uses", ("",))[0].startswith("actions/upload-artifact@"))
        self.assertEqual(upload["if"], ("${{ always() && steps.checkout.outcome == 'success' && "
                         "steps.hosted.outputs.encrypted_retention_ready == 'true' }}", []))
        self.assertTrue(any(row.get("id", (None,))[0] == "hosted" for row in steps))
        options = children(upload, "with", 10)
        self.assertEqual(options["path"], ("|", [
            "            ${{ runner.temp }}/p06-qualified-warm-attempt/public/qualified-warm-retention.tar.age",
            "            ${{ runner.temp }}/p06-qualified-warm-attempt/public/encryption-summary.json"]))
        self.assertEqual(options["include-hidden-files"], ("false", []))
        self.assertEqual(options["if-no-files-found"], ("error", []))
        self.assertNotIn("*", "\n".join(options["path"][1]))


if __name__ == "__main__":
    unittest.main()
