# SPDX-License-Identifier: Apache-2.0
"""Hosted artifact admission is mandatory before provisioning or private/native work."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import p06_qualified_warm_hosted as hosted
import test_p06_qualified_warm_hosted as fixtures


REVISION = fixtures.REVISION
REAL_PREFLIGHT = hosted.preflight
REAL_REPLAY = hosted.governance_replay.verify_archive
ORIGINAL = b"inert governance original fixture\n"
DIGEST = hashlib.sha256(ORIGINAL).hexdigest()


def replay_receipt():
    return {"schema_version": 1, "scope": "project-governance-artifact-replay-only",
            "independent_packet_replay": True, "revision": REVISION,
            "archive": {"bytes": len(ORIGINAL), "sha256": DIGEST},
            "canonical_tests": 5, "successful_subtests": 7, "events": 17,
            "provider_authenticated": False, "retained_code_executed": False,
            "trusted_source_imported": True, "tests_executed_by_replay": False,
            "native_acceptance": False, "phase_acceptance": False, "performance_acceptance": False}


class GovernanceAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.output = self.root / "hosted"
        self.output.mkdir(mode=0o700)
        self.snapshot = {"revision": REVISION, "tree": "b" * 40, "dirty": False}
        self.documents = fixtures.governance()
        self.after = deepcopy(self.documents)
        self.replayed = False
        self.timeline, self.requests, self.downloaded = [], [], []
        self.receipt = replay_receipt()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.source_mock = self.stack.enter_context(mock.patch.object(
            hosted, "verify_source", side_effect=self.observe_source))
        self.api_mock = self.stack.enter_context(mock.patch.object(hosted, "_api", side_effect=self.api))
        self.download_mock = self.stack.enter_context(mock.patch.object(
            hosted.governance_artifact, "download_artifact", side_effect=self.download))
        self.replay_mock = self.stack.enter_context(mock.patch.object(
            hosted.governance_replay, "verify_archive", side_effect=self.replay))

    def observe_source(self, source, revision):
        self.assertEqual(revision, REVISION)
        self.timeline.append("source-after" if self.replayed else "source-before")
        return deepcopy(self.snapshot)

    def api(self, path, token):
        self.assertEqual(token, "token_fixture")
        self.requests.append(path)
        self.timeline.append("provider-after" if self.replayed else "provider-before")
        prefix = "/repos/" + hosted.REPOSITORY + "/actions/"
        index = {prefix + "workflows/project-governance.yml": 0,
                 prefix + "runs/123/attempts/2/jobs?per_page=100": 2,
                 prefix + "runs/123": 3}.get(path)
        if path.startswith(prefix + "workflows/project-governance.yml/runs?"):
            self.assertFalse(self.replayed, "admission must not reselect a newer run after replay")
            self.assertIn("head_sha=" + REVISION, path)
            index = 1
        self.assertIsNotNone(index, "unexpected provider observation endpoint")
        return deepcopy((self.after if self.replayed else self.documents)[index])

    def download(self, revision, run_id, run_attempt, token, output_dir, *, api):
        self.assertEqual((revision, run_id, run_attempt, token), (REVISION, 123, 2, "token_fixture"))
        self.assertIs(api, hosted._api)
        self.timeline.append("download")
        directory = Path(output_dir)
        directory.mkdir(mode=0o700)
        archive = directory / "governance.zip"
        archive.write_bytes(ORIGINAL)
        archive.chmod(0o600)
        self.downloaded.append(archive)
        return {"archive_path": str(archive), "artifact_id": 789,
                "artifact_name": f"project-governance-{REVISION}-run123-attempt2",
                "sha256": DIGEST, "bytes": len(ORIGINAL), "repository": hosted.REPOSITORY,
                "head_sha": REVISION, "run_id": 123, "run_attempt": 2,
                "provider_observed_stable": True}

    def replay(self, path, *, revision, source_dir, expected_sha256):
        self.assertEqual(Path(path).read_bytes(), ORIGINAL)
        self.assertEqual((revision, expected_sha256), (REVISION, DIGEST))
        self.assertTrue(Path(source_dir).is_dir())
        self.timeline.append("replay")
        self.replayed = True
        return deepcopy(self.receipt)

    def preflight(self, **kwargs):
        return REAL_PREFLIGHT(self.source, REVISION, fixtures.context(), **kwargs)

    def assert_rejected(self, **kwargs):
        with self.assertRaises(hosted.HostedError) as error:
            self.preflight(**kwargs)
        self.assertEqual(str(error.exception), "governance_admission")

    def test_exact_original_and_scoped_receipt_precede_stable_provider_observation(self):
        result = self.preflight(output_parent=self.output)
        self.assertEqual(set(result), {"context", "source", "governance"})
        governance = result["governance"]
        self.assertIs(governance["independent_packet_replay"], True)
        self.assertIs(governance["provider_observed_stable"], True)
        self.assertIs(governance["source_observed_stable"], True)
        self.assertEqual(governance["run_attempt"], 2)
        self.assertEqual(governance["job_id"], 456)
        self.assertIs(governance["replay"]["provider_authenticated"], False)
        self.assertEqual(self.timeline, ["source-before", *("provider-before",) * 4,
                         "download", "replay", "source-after", *("provider-after",) * 4,
                         "source-after"])
        self.assertEqual(self.source_mock.call_count, 3)
        self.download_mock.assert_called_once()
        self.replay_mock.assert_called_once()
        directory = self.output / "governance"
        self.assertEqual({path.name for path in directory.iterdir()},
                         {"governance.zip", "provider.json", "replay.json"})
        self.assertEqual((directory / "governance.zip").read_bytes(), ORIGINAL)
        self.assertEqual((directory / "governance.zip").stat().st_nlink, 1)
        self.assertEqual(list(self.output.rglob("*.zip")), [directory / "governance.zip"])
        self.assertEqual(json.loads((directory / "replay.json").read_text()), governance["replay"])
        provider = json.loads((directory / "provider.json").read_text())
        self.assertEqual(provider, {key: value for key, value in governance.items() if key != "replay"})
        retained = json.dumps(result)
        for private in (str(self.root), "token_fixture", fixtures.SECRET, "archive_path"):
            self.assertNotIn(private, retained)

    def test_standalone_temporary_original_is_removed_on_success_and_failure(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                self.replayed = False
                self.replay_mock.side_effect = ValueError(fixtures.SECRET) if fail else self.replay
                with mock.patch.dict(os.environ, {"TMPDIR": str(self.source)}):
                    if fail:
                        self.assert_rejected()
                    else:
                        self.preflight()
                archive = self.downloaded[-1]
                self.assertEqual(archive.parents[2], Path("/tmp"))
                self.assertFalse(archive.parent.parent.exists())
                self.assertEqual(list(self.source.iterdir()), [])

    def test_existing_or_overlapping_output_never_overwrites_an_original(self):
        directory = self.output / "governance"
        directory.mkdir()
        original = directory / "governance.zip"
        original.write_bytes(b"previous original")
        self.assert_rejected(output_parent=self.output)
        self.assertEqual(original.read_bytes(), b"previous original")
        self.replay_mock.assert_not_called()
        self.download_mock.reset_mock()
        for parent in (self.source, self.source / "missing"):
            with self.subTest(parent=parent):
                self.assert_rejected(output_parent=parent)
        symlink = self.root / "linked-hosted"
        symlink.symlink_to(self.output, target_is_directory=True)
        self.assert_rejected(output_parent=symlink)
        self.download_mock.assert_not_called()

    def test_changed_original_provider_run_attempt_job_or_workflow_rejects(self):
        changes = ((0, "id", 43), (0, "state", "disabled_manually"),
                   (3, "id", 124), (3, "run_attempt", 3), (3, "head_sha", "b" * 40),
                   (3, "event", "workflow_dispatch"), (3, "conclusion", "failure"),
                   (3, "updated_at", "changed-provider-record"))
        for index, key, value in changes:
            with self.subTest(index=index, key=key):
                self.after = deepcopy(self.documents)
                self.after[index][key] = value
                self.replayed = False
                self.assert_rejected()
        for key, value in (("id", 457), ("run_id", 124), ("run_attempt", 3),
                           ("conclusion", "failure"), ("completed_at", "changed-provider-record")):
            with self.subTest(job_key=key):
                self.after = deepcopy(self.documents)
                self.after[2]["jobs"][0][key] = value
                self.replayed = False
                self.assert_rejected()

    def test_run_change_during_final_job_observation_is_rejected(self):
        calls = 0

        def changed(path, token):
            nonlocal calls
            result = self.api(path, token)
            if self.replayed and path.endswith("/runs/123"):
                calls += 1
                if calls == 2:
                    result["run_attempt"] = 3
            return result

        self.api_mock.side_effect = changed
        self.assert_rejected()
        self.assertEqual(calls, 2)

    def test_source_change_after_replay_or_provider_reobservation_is_rejected(self):
        for change_index in (1, 2):
            with self.subTest(change_index=change_index):
                snapshots = [deepcopy(self.snapshot) for _ in range(3)]
                snapshots[change_index]["tree"] = "c" * 40
                self.source_mock.side_effect = snapshots
                self.replayed = False
                self.assert_rejected()

    def test_artifact_provider_identity_and_exact_downloaded_bytes_must_agree(self):
        changes = {"artifact_id": True, "artifact_name": "lookalike", "repository": "fork/AI-GPU",
                   "head_sha": "b" * 40, "run_id": 124, "run_attempt": True,
                   "provider_observed_stable": False, "bytes": True, "sha256": "0" * 64}
        for key, value in changes.items():
            with self.subTest(key=key):
                def wrong(*args, **kwargs):
                    return dict(self.download(*args, **kwargs), **{key: value})

                self.download_mock.side_effect = wrong
                self.assert_rejected()
        self.replay_mock.assert_not_called()

    def test_artifact_path_substitution_and_hardlink_alias_are_rejected(self):
        unrelated = self.root / "unrelated.zip"
        unrelated.write_bytes(ORIGINAL)

        def replaced(*args, **kwargs):
            result = self.download(*args, **kwargs)
            result["archive_path"] = str(unrelated)
            return result

        self.download_mock.side_effect = replaced
        self.assert_rejected()
        self.replay_mock.assert_not_called()

        def aliased(*args, **kwargs):
            result = self.download(*args, **kwargs)
            os.link(result["archive_path"], Path(result["archive_path"]).with_suffix(".alias"))
            return result

        self.download_mock.side_effect = aliased
        self.assert_rejected()
        self.replay_mock.assert_not_called()

    def test_replay_scope_digest_revision_and_false_claims_are_required(self):
        changes = {"schema_version": True, "revision": "b" * 40, "scope": "native-acceptance",
                   "independent_packet_replay": False, "provider_authenticated": True,
                   "retained_code_executed": True, "trusted_source_imported": False,
                   "tests_executed_by_replay": True, "native_acceptance": True,
                   "phase_acceptance": True, "performance_acceptance": True,
                   "archive": {"bytes": len(ORIGINAL), "sha256": "0" * 64}}
        for key, value in changes.items():
            with self.subTest(key=key):
                self.receipt = dict(replay_receipt(), **{key: value})
                self.replayed = False
                self.assert_rejected()
        self.receipt = {"independent_packet_replay": True}
        self.replayed = False
        self.assert_rejected()

    def test_original_changed_during_replay_cannot_admit_or_leave_success_receipts(self):
        def changed(path, **kwargs):
            result = self.replay(path, **kwargs)
            Path(path).write_bytes(b"X" * len(ORIGINAL))
            return result

        self.replay_mock.side_effect = changed
        self.assert_rejected(output_parent=self.output)
        self.assertFalse((self.output / "governance/replay.json").exists())
        self.assertFalse((self.output / "governance/provider.json").exists())

    def test_real_reader_rejects_truncated_original_without_importing_source(self):
        self.replay_mock.side_effect = REAL_REPLAY
        with mock.patch.object(hosted.governance_replay, "_collect") as collect:
            self.assert_rejected(output_parent=self.output)
        collect.assert_not_called()
        self.assertEqual((self.output / "governance/governance.zip").read_bytes(), ORIGINAL)
        self.assertFalse((self.output / "governance/replay.json").exists())

    def test_public_preflight_failures_never_expose_provider_errors_or_retained_paths(self):
        for selected in (self.source_mock, self.api_mock, self.download_mock, self.replay_mock):
            with self.subTest(selected=selected):
                previous = selected.side_effect
                selected.side_effect = ValueError(fixtures.SECRET + " token_fixture " + str(self.root))
                self.replayed = False
                stdout, stderr = io.StringIO(), io.StringIO()
                try:
                    with mock.patch.dict(os.environ, fixtures.context(), clear=True), \
                            redirect_stdout(stdout), redirect_stderr(stderr):
                        status = hosted.main(["preflight", "--source-dir", str(self.source),
                                              "--expected-revision", REVISION])
                finally:
                    selected.side_effect = previous
                self.assertEqual(status, 1)
                self.assertEqual(json.loads(stdout.getvalue()), {
                    "contract_id": hosted.CONTRACT_ID, "expected_revision": REVISION,
                    "stage": "preflight", "outcome": "fail"})
                self.assertEqual(stderr.getvalue(), "")

    def test_admission_failures_never_provision_acquire_private_inputs_or_start_native(self):
        for failure in ("source", "provider", "download", "replay", "post-provider", "post-source"):
            with self.subTest(failure=failure), ExitStack() as local:
                case = fixtures.HostedCompositionTests()
                case.setUp()
                local.callback(case.doCleanups)
                local.enter_context(mock.patch.object(hosted, "preflight", new=REAL_PREFLIGHT))
                age = local.enter_context(mock.patch.object(hosted, "provision_age"))
                host = local.enter_context(mock.patch.object(hosted, "provision_host"))
                self.replayed = False
                self.after = deepcopy(self.documents)
                if failure == "post-provider":
                    self.after[2]["jobs"][0]["id"] += 1
                elif failure == "post-source":
                    local.enter_context(mock.patch.object(hosted, "verify_source", side_effect=[
                        deepcopy(self.snapshot), dict(self.snapshot, tree="c" * 40)]))
                else:
                    target, name = {"source": (hosted, "verify_source"),
                                    "provider": (hosted, "_api"),
                                    "download": (hosted.governance_artifact, "download_artifact"),
                                    "replay": (hosted.governance_replay, "verify_archive")}[failure]
                    local.enter_context(mock.patch.object(target, name, side_effect=ValueError(fixtures.SECRET)))
                result = case.execute()
                self.assertEqual(result["outcome"], "fail")
                self.assertEqual(result["native_execution"], "not_run")
                self.assertFalse(result["orchestration_passed"])
                age.assert_not_called()
                host.assert_not_called()
                self.assertEqual([row["module"] for row in case.calls],
                                 ["p06_qualified_warm_pack", "p06_qualified_warm_encrypt"])
                packed = case.calls[0]["argv"]
                self.assertIn("partial", packed)
                self.assertIn("hosted=" + str(case.attempt / "hosted"), packed)
                if failure in ("replay", "post-provider", "post-source"):
                    original = case.attempt / "hosted/governance/governance.zip"
                    self.assertEqual(original.read_bytes(), ORIGINAL)
                    self.assertEqual(original.stat().st_nlink, 1)

    def test_execute_retains_replayed_original_inside_existing_encrypted_selection(self):
        case = fixtures.HostedCompositionTests()
        case.setUp()
        try:
            with mock.patch.object(hosted, "preflight", new=REAL_PREFLIGHT):
                result = case.execute()
            self.assertEqual(result["outcome"], "pass")
            governance = result["preflight"]["governance"]
            self.assertTrue(governance["independent_packet_replay"])
            self.assertFalse(governance["replay"]["provider_authenticated"])
            original = case.attempt / "hosted/governance/governance.zip"
            self.assertEqual(original.read_bytes(), ORIGINAL)
            self.assertEqual(original.stat().st_nlink, 1)
            self.assertEqual(list(case.attempt.rglob("governance.zip")), [original])
            packed = next(row for row in case.calls if row["module"] == "p06_qualified_warm_pack")
            self.assertIn("hosted=" + str(case.attempt / "hosted"), packed["argv"])
        finally:
            case.doCleanups()


if __name__ == "__main__":
    unittest.main()
