# SPDX-License-Identifier: Apache-2.0
"""Original and independently rehashed hosted-envelope replay controls."""

import hashlib
from pathlib import Path
import re
import tempfile
import unittest

import p06_managed_preflight_contract as contract
from p06_managed_preflight_replay_hosted import OUTER_FILES, _valid_hosted_ref
from p06_managed_preflight_replay_test_support import Packet, replay
from p06_replay import ReplayError


class ManagedPreflightHostedReplayTests(unittest.TestCase):
    def modified(self, change, *, prefix="managed-preflight"):
        with tempfile.TemporaryDirectory(prefix="p06-hosted-test-") as directory, Packet() as packet:
            change(packet)
            path = Path(directory) / "mutation.zip"
            digest = packet.write(path)
            return replay(path, digest, prefix=prefix)

    def rejects(self, change, reason, **kwargs):
        with self.assertRaisesRegex(ReplayError, re.escape(reason)):
            self.modified(change, **kwargs)

    def test_original_binds_all_outer_members_and_preserves_claim_limits(self):
        result = replay()
        hosted = result["hosted_identity"]
        self.assertEqual(hosted["validation"], "pass")
        self.assertEqual({row["path"] for row in hosted["outer_files"]}, set(OUTER_FILES))
        self.assertEqual(hosted["job"]["GITHUB_RUN_ID"], "45085300171")
        self.assertEqual(hosted["job"]["GITHUB_RUN_ATTEMPT"], "1")
        self.assertEqual(hosted["preparation"]["cache_quarantine_state"], "relocated")
        self.assertIs(hosted["origin_authenticated"], False)
        self.assertIs(hosted["host_installation_log_semantics_verified"], False)
        self.assertIs(hosted["preparation"]["dependency_compilation_provenance_verified"], False)
        self.assertEqual(result["native_execution"], "not_run")
        self.assertIs(result["retained_code_executed"], False)
        for name in contract.FALSE_CLAIMS:
            self.assertIs(result[name], False)

    def test_missing_outer_member_is_rejected(self):
        self.rejects(lambda packet: packet.__delitem__("host-dependencies.log"),
                     "complete hosted archive inventory")

    def test_unexpected_outer_member_is_rejected(self):
        self.rejects(lambda packet: packet.__setitem__("unbound.txt", b"extra\n"),
                     "complete hosted archive inventory")

    @staticmethod
    def wrap(packet):
        for name in tuple(packet):
            packet["bundle/" + name] = packet[name]
            del packet[name]

    def test_complete_wrapped_archive_is_supported(self):
        result = self.modified(self.wrap, prefix="bundle/managed-preflight")
        self.assertEqual(result["hosted_identity"]["validation"], "pass")

    def test_member_outside_selected_outer_parent_is_rejected(self):
        def change(packet):
            self.wrap(packet)
            packet["unbound.txt"] = b"outside the selected parent\n"
        self.rejects(change, "whole archive hosted inventory", prefix="bundle/managed-preflight")

    def test_workflow_mutation_is_rejected_even_with_matching_job_digest(self):
        def change(packet):
            body = packet["workflow.yml"] + b"\n# changed retained workflow\n"
            packet["workflow.yml"] = body
            packet.edit_json("job.json", lambda row: row.update(
                workflow_sha256=hashlib.sha256(body).hexdigest()))
        self.rejects(change, "hosted workflow source bytes")

    def test_job_source_revision_must_match_independent_revision(self):
        self.rejects(lambda packet: packet.edit_json("job.json", lambda row: row.update(
            GITHUB_SHA="0" * 40)), "hosted job GITHUB_SHA")

    def test_job_claim_promotion_is_rejected(self):
        for name in contract.FALSE_CLAIMS:
            with self.subTest(claim=name):
                self.rejects(lambda packet: packet.edit_json("job.json", lambda row: row.update(
                    {name: True})), "hosted job " + name)

    def test_job_resource_receipt_must_meet_original_gate(self):
        for name, value, reason in (
            ("free_disk_bytes_before_cache", 15 * 1024**3 - 1, "hosted initial disk"),
            ("available_memory_bytes_before_cache", True, "hosted initial memory"),
        ):
            with self.subTest(resource=name):
                self.rejects(lambda packet: packet.edit_json("job.json", lambda row: row.update(
                    {name: value})), reason)

    def test_job_attempt_identity_cannot_be_zero(self):
        self.rejects(lambda packet: packet.edit_json("job.json", lambda row: row.update(
            GITHUB_RUN_ATTEMPT="0")), "invalid hosted run identity")

    def test_push_ref_must_match_master_workflow(self):
        self.rejects(lambda packet: packet.edit_json("job.json", lambda row: row.update(
            GITHUB_REF="refs/heads/other")), "hosted push ref")

    def test_dispatch_ref_must_be_a_valid_branch_or_tag(self):
        self.rejects(lambda packet: packet.edit_json("job.json", lambda row: row.update(
            GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_REF="refs/heads/topic..name")),
            "invalid hosted Git ref")
        self.rejects(lambda packet: packet.edit_json("job.json", lambda row: row.update(
            GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_REF="refs/pull/1/merge")),
            "hosted dispatch ref differs")

    def test_hosted_ref_grammar_rejects_git_metacharacters_and_invalid_components(self):
        for value in (None, True, "", "refs/heads/.hidden", "refs/heads/topic.lock",
                      "refs/heads/a//b", "refs/heads/topic.", "refs/heads/topic@{1}",
                      "refs/heads/a~b", "refs/heads/a\\b", "refs/heads/a\x00b",
                      "refs/heads/a:b", "refs/heads/a?b", "refs/heads/a*b",
                      "refs/heads/a[b", "refs/heads/" + "a" * 1024):
            with self.subTest(ref=value):
                self.assertFalse(_valid_hosted_ref(value))
        for value in ("refs/heads/master", "refs/heads/topic/trace-1", "refs/tags/v1.2.3",
                      "refs/pull/12/merge"):
            with self.subTest(ref=value):
                self.assertTrue(_valid_hosted_ref(value))

    def test_preparation_source_state_must_equal_native_checkout(self):
        self.rejects(lambda packet: packet.edit_json("preparation.json", lambda row:
            row["source"].update(dirty=True)), "hosted preparation source.dirty")

    def test_preparation_cache_keys_must_bind_retained_sources_and_toolchain(self):
        for name, value, reason in (
            ("third_party_cache_key", "Linux-thirdparty-" + "0" * 64,
             "preparation dependency cache source identity"),
            ("toolchain_cache_key", "Linux-toolchain-unrelated-full",
             "preparation toolchain cache identity differs"),
        ):
            with self.subTest(cache=name):
                self.rejects(lambda packet: packet.edit_json("preparation.json", lambda row:
                    row.update({name: value})), reason)

    def test_preparation_resource_receipt_must_meet_original_gate(self):
        self.rejects(lambda packet: packet.edit_json("preparation.json", lambda row:
            row["resources"]["free_disk_bytes"].update(workspace=15 * 1024**3 - 1)),
            "preparation disk reserve")

    def test_preparation_quarantine_requires_unchanged_moved_bytes(self):
        self.rejects(lambda packet: packet.edit_json("preparation.json", lambda row:
            row["cache_quarantine"]["files"][0].update(after_sha256="0" * 64)),
            "quarantine product after_sha256")

    def test_preparation_quarantine_cannot_omit_declared_module(self):
        self.rejects(lambda packet: packet.edit_json("preparation.json", lambda row:
            row.update(cache_quarantine={"submodule": "third_party/cocogfx",
                                         "state": "not_present", "files": []})),
            "quarantine omits a declared submodule")

    def test_preparation_terminal_output_cannot_claim_execution(self):
        self.rejects(lambda packet: packet.edit_json("preparation.log", lambda row:
            row.update(native_execution="run")), "preparation terminal output.native_execution")

    def test_provisioned_python_must_equal_recorded_executing_tool(self):
        self.rejects(lambda packet: packet.edit_json("python-provision.json", lambda row:
            row.update(executable="/unrelated/python3")),
            "provisioned executable differs from the executing interpreter")

    def test_execution_terminal_counts_must_equal_recomputed_population(self):
        self.rejects(lambda packet: packet.edit_json("execution.log", lambda row:
            row["completed_counts"].update(launches=131)),
            "hosted execution terminal output.completed_counts.launches")

    def test_host_installation_log_is_retained_without_provenance_promotion(self):
        body = b"opaque host installation output; no execution claim\n"
        result = self.modified(lambda packet: packet.__setitem__("host-dependencies.log", body))
        hosted = result["hosted_identity"]
        identity = next(row for row in hosted["outer_files"] if row["path"] == "host-dependencies.log")
        self.assertEqual(identity["sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(identity["size_bytes"], len(body))
        self.assertIs(hosted["host_installation_log_semantics_verified"], False)
        self.assertIs(result["dependency_compilation_provenance_verified"], False)


if __name__ == "__main__":
    unittest.main()
