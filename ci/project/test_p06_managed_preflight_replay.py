# SPDX-License-Identifier: Apache-2.0
"""Complete original replay, contract rejection, and explicit CLI trust anchors."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import p06_managed_preflight_contract as contract
import p06_managed_preflight_records as records
import p06_managed_preflight_replay as reader
import p06_managed_preflight_replay_test_support as fixture
from p06_replay import ReplayError


COUNTS = {
    "available_queries": 528, "cache_flush_reads": 132, "checked_words": 4224,
    "dcr_reads": 1188, "half_replies": 1056, "launches": 132, "processes": 4,
    "snapshots": 16, "unavailable_rows": 192,
}
SCRIPT = fixture.ROOT / "ci/project/p06_managed_preflight_replay.py"
TREE = "cd61992a845ad14cbebd24b930c5801f727d5b41"
CLI_INPUTS = {
    "--archive": str(fixture.ORIGINAL), "--sha256": fixture.ORIGINAL_SHA256,
    "--source-revision": fixture.REVISION,
    "--source-inventory": str(fixture.SOURCE_INVENTORY),
    "--source-inventory-sha256": fixture.SOURCE_INVENTORY_SHA256,
    "--source-derivation": str(fixture.SOURCE_DERIVATION),
    "--source-derivation-sha256": fixture.SOURCE_DERIVATION_SHA256,
}
FAILED_INPUTS = {
    "--archive": str(fixture.FAILED_ORIGINAL), "--sha256": fixture.FAILED_SHA256,
    "--source-revision": fixture.FAILED_REVISION,
    "--source-inventory": str(fixture.FAILED_INVENTORY),
    "--source-inventory-sha256": fixture.FAILED_INVENTORY_SHA256,
    "--source-derivation": str(fixture.FAILED_DERIVATION),
    "--source-derivation-sha256": fixture.FAILED_DERIVATION_SHA256,
}


class ManagedPreflightReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = fixture.replay()

    def rejected_report(self, change, reason):
        with tempfile.TemporaryDirectory(prefix="p06-replay-contract-") as directory, fixture.Packet() as packet:
            packet.edit_report(change)
            path = Path(directory) / "mutation.zip"
            digest = packet.write(path)
            self.assertNotEqual(digest, fixture.ORIGINAL_SHA256)
            with self.assertRaisesRegex(ReplayError, re.escape(reason)):
                fixture.replay(path, digest)

    def cli(self, inputs=None, *, output=None):
        args = dict(CLI_INPUTS if inputs is None else inputs)
        if output is not None:
            args["--output"] = str(output)
        return subprocess.run([sys.executable, str(SCRIPT),
            *(item for pair in args.items() for item in pair)],
            cwd=fixture.ROOT, env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1",
                                   "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
            capture_output=True, text=True, timeout=45, check=False)

    def assert_failed_cli(self, result, reason):
        self.assertEqual(result.returncode, 1, result.stderr)
        row = json.loads(result.stdout)
        self.assertEqual(row["outcome"], "fail")
        self.assertIn(reason, row["reason"])
        self.assertEqual(row["native_execution"], "not_run")
        self.assertIs(row["retained_code_executed"], False)
        self.assertIs(row["dependency_compilation_provenance_verified"], False)
        for name in contract.FALSE_CLAIMS:
            self.assertIs(row[name], False)

    def test_original_recomputes_population_payloads_builds_and_external_pins(self):
        row = self.original
        self.assertEqual(row["contract_id"], "p06-managed-counter-preflight-replay-v1")
        self.assertEqual(row["outcome"], "pass")
        self.assertEqual(row["counts"], COUNTS)
        self.assertEqual(row["source_revision"], fixture.REVISION)
        self.assertEqual(row["source_tree"], TREE)
        self.assertEqual(row["source_inventory_sha256"], fixture.SOURCE_INVENTORY_SHA256)
        self.assertEqual(row["source_derivation_sha256"], fixture.SOURCE_DERIVATION_SHA256)
        self.assertEqual(row["source_derivation"]["source_tree"], TREE)
        self.assertEqual(row["source_derivation"]["repository_source_counts"], {
            "source": 806, "ramulator": 50, "softfloat": 7, "spdlog": 99, "yaml-cpp": 37})
        self.assertEqual(row["commands_checked"], 35)
        self.assertEqual(row["retained_source_files_checked"], 999)
        self.assertEqual(row["retained_files_checked"], 1172)
        self.assertEqual(row["retained_payload_files_checked"], 17)
        self.assertEqual(row["retained_payload_bytes_checked"], 13315886)
        self.assertEqual(row["archive_read"]["data_files"], 1215)
        self.assertEqual(row["archive_read"]["archive"]["sha256"], fixture.ORIGINAL_SHA256)
        self.assertEqual(row["archive_read"]["archive"]["size_bytes"], 8661838)
        self.assertEqual(set(row["application_builds"]), {"simx-fp16", "simx-bf16"})
        for build in row["application_builds"].values():
            self.assertEqual(build["command_count"], 30)
            self.assertEqual(build["command_counts"]["riscv_compile"], 14)
            self.assertEqual(build["command_counts"]["kernel_clang"], 5)
        self.assertEqual(len(row["processes"]), 4)
        for process in row["processes"]:
            self.assertEqual((process["launches"], process["checked_words"], process["snapshots"],
                              process["half_replies"], process["cache_flush_reads"], process["dcr_reads"]),
                             (33, 1056, 4, 264, 33, 297))

    def test_original_keeps_unearned_claims_false_and_identifies_current_readers(self):
        row = self.original
        self.assertEqual(row["native_execution"], "not_run")
        self.assertIs(row["retained_code_executed"], False)
        self.assertIs(row["dependency_compilation_provenance_verified"], False)
        for name in contract.FALSE_CLAIMS:
            self.assertIs(row[name], False)
        self.assertEqual(row["unresolved_obligations"], [
            "all_40_component_lifetime_and_pending_balance",
            "dependency_source_to_loaded_binary_provenance",
            "independent_complete_counter_qualification"])
        identities = {item["path"]: item for item in row["trusted_replay_sources"]}
        expected = {"ci/project/" + name + ".py" for name in reader.READER_MODULES}
        self.assertTrue(expected <= set(identities))
        self.assertIn("ci/project/p06_managed_preflight_replay.py", identities)
        for name, identity in identities.items():
            body = (fixture.ROOT / name).read_bytes()
            self.assertEqual(identity["sha256"], hashlib.sha256(body).hexdigest())
            self.assertEqual(identity["size_bytes"], len(body))
        self.assertEqual(row["trusted_archive_reader"]["sha256"],
            "4144becd4fe3c829380f7e66cdb66f7cf073b5e189c2620cd60c62940b9317d3")

    def test_failed_original_is_rejected_at_its_failed_outcome(self):
        with self.assertRaisesRegex(ReplayError, r"^report\.outcome: value differs$"):
            fixture.replay(fixture.FAILED_ORIGINAL, fixture.FAILED_SHA256,
                revision=fixture.FAILED_REVISION, inventory=fixture.FAILED_INVENTORY,
                inventory_sha256=fixture.FAILED_INVENTORY_SHA256,
                derivation=fixture.FAILED_DERIVATION, derivation_sha256=fixture.FAILED_DERIVATION_SHA256)

    def test_report_schema_unknown_fields_and_contract_are_exact(self):
        for fields, reason in (
            ({"schema_version": True}, "report.schema_version: value type differs"),
            ({"contract_id": "different-contract"}, "report.contract_id"),
            ({"extra": False}, "managed preflight report: missing or unknown fields"),
        ):
            with self.subTest(fields=fields):
                self.rejected_report(lambda row: row.update(fields), reason)

    def test_each_unearned_report_claim_rejects_promotion(self):
        for name in contract.FALSE_CLAIMS:
            with self.subTest(claim=name):
                self.rejected_report(lambda row: row.update({name: True}), "report." + name)

    def test_process_variant_command_and_completed_population_cannot_shrink(self):
        for change, reason in (
            (lambda row: row["processes"].pop(), "expected exactly four managed processes"),
            (lambda row: row["variants"].pop(), "expected two format builds"),
            (lambda row: row["commands"].pop(), "unexpected command inventory"),
            (lambda row: row["completed_counts"].update(checked_words=4223),
             "report.completed_counts.checked_words"),
        ):
            with self.subTest(reason=reason):
                self.rejected_report(change, reason)

    def test_fixed_resource_policy_and_build_parallelism_cannot_be_widened(self):
        for name, value, reason in (
            ("threads", 2, "budget.threads"),
            ("max_rss_bytes", 4 * 1024**3 + 1, "budget.max_rss_bytes"),
            ("jobs", 3, "build jobs"),
        ):
            with self.subTest(field=name):
                self.rejected_report(lambda row: row["budget"].update({name: value}), reason)

    def test_observed_reserves_must_satisfy_original_disk_and_memory_gates(self):
        self.rejected_report(lambda row: row["resources_after"]["free_disk_bytes"].update(
            output=15 * 1024**3 - 1), "resources_after disk reserve")
        self.rejected_report(lambda row: row["resources_before"].update(
            available_memory_bytes=4 * 1024**3 - 1), "initial memory reserve")

    def test_command_identity_execution_context_and_success_metadata_are_exact(self):
        for field, value, reason in (
            ("argv", ["/usr/bin/g++", "--unrecorded-option"], "command version-gpp.argv"),
            ("cwd", "/unrelated/build", "command version-gpp.cwd"),
            ("environment", {}, "command version-gpp.environment"),
            ("native_process", True, "command version-gpp.native_process"),
            ("exit_code", 1, "command version-gpp.exit_code"),
            ("cleanup_complete", False, "command version-gpp.cleanup_complete"),
        ):
            with self.subTest(field=field):
                self.rejected_report(lambda row: row["commands"][0].update({field: value}), reason)

    def test_command_duration_rss_and_log_bytes_have_numeric_bounds(self):
        for field, value, reason in (
            ("duration_seconds", -1, "command duration"),
            ("duration_seconds", True, "command duration"),
            ("peak_rss_bytes", 4 * 1024**3 + 1, "command peak RSS"),
            ("log_size_bytes", 16 * 1024**2 + 1, "command log size"),
        ):
            with self.subTest(field=field, value=value):
                self.rejected_report(lambda row: row["commands"][0].update({field: value}), reason)

    def test_stability_observations_have_complete_ordered_chronology(self):
        for change, reason in (
            (lambda row: row["stability_checks"].pop(), "missing stability observations"),
            (lambda row: row["stability_checks"][0].update(label="after-command-version-gpp"),
             "stability order"),
            (lambda row: row["stability_checks"][0].update(at="2099-01-01T00:00:00+00:00"),
             "stability timestamps are outside chronology"),
        ):
            with self.subTest(reason=reason):
                self.rejected_report(change, reason)

    def test_stability_observation_hashes_must_bind_original_inputs(self):
        self.rejected_report(lambda row: row["stability_checks"][-1].update(source_sha256="0" * 64),
                             "stability identity source")

    def test_raw_logs_and_retained_descriptors_are_complete_and_unique(self):
        self.rejected_report(lambda row: row["raw_logs"].pop(), "original raw-log inventory")
        self.rejected_report(lambda row: row["retained_files"].append(row["retained_files"][0]),
                             "complete retained inventory: repeated path")

    def test_original_executing_helpers_must_match_complete_pinned_sources(self):
        self.rejected_report(lambda row: row["loaded_helpers"].pop(), "executing helpers paths")
        self.rejected_report(lambda row: row["loaded_helpers"][0].update(sha256="0" * 64),
                             "executing helper identity.sha256")

    def test_cli_requires_each_explicit_external_input(self):
        for name in CLI_INPUTS:
            with self.subTest(argument=name):
                args = dict(CLI_INPUTS)
                del args[name]
                result = self.cli(args)
                self.assertEqual(result.returncode, 2)
                self.assertIn("the following arguments are required: " + name, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_cli_rejects_each_wrong_digest_and_leaves_no_output(self):
        for name, reason in (
            ("--sha256", "original ZIP SHA-256 differs from the external intake identity"),
            ("--source-inventory-sha256", "source manifest SHA-256 differs from the external digest"),
            ("--source-derivation-sha256", "source derivation external digest"),
        ):
            with self.subTest(argument=name), tempfile.TemporaryDirectory(prefix="p06-replay-cli-") as directory:
                output = Path(directory) / "result.json"
                self.assert_failed_cli(self.cli(dict(CLI_INPUTS, **{name: "0" * 64}), output=output), reason)
                self.assertFalse(output.exists())

    def test_cli_original_writes_a_complete_success_receipt(self):
        with tempfile.TemporaryDirectory(prefix="p06-replay-cli-") as directory:
            output = Path(directory) / "result.json"
            result = self.cli(output=output)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            terminal = json.loads(result.stdout)
            self.assertEqual(terminal["outcome"], "pass")
            self.assertEqual(terminal["counts"], COUNTS)
            self.assertEqual(terminal["report"], str(output))
            stored = json.loads(output.read_text())
            self.assertEqual(stored["source_tree"], TREE)
            self.assertEqual(stored["counts"], COUNTS)
            self.assertEqual(stored["source_derivation_sha256"], fixture.SOURCE_DERIVATION_SHA256)
            for name in contract.FALSE_CLAIMS:
                self.assertIs(terminal[name], False)
                self.assertIs(stored[name], False)

    def test_cli_output_creation_is_exclusive(self):
        with tempfile.TemporaryDirectory(prefix="p06-replay-cli-") as directory:
            output = Path(directory) / "result.json"
            sentinel = b"existing user output\n"
            output.write_bytes(sentinel)
            self.assert_failed_cli(self.cli(output=output), "File exists")
            self.assertEqual(output.read_bytes(), sentinel)

    def test_cli_failed_original_returns_the_original_failure_without_a_receipt(self):
        with tempfile.TemporaryDirectory(prefix="p06-replay-cli-") as directory:
            output = Path(directory) / "result.json"
            self.assert_failed_cli(self.cli(FAILED_INPUTS, output=output), "report.outcome: value differs")
            self.assertFalse(output.exists())

    def test_shadowed_trusted_helper_is_rejected_before_any_input_is_opened(self):
        with mock.patch.object(records, "__file__", "/untrusted/p06_managed_preflight_records.py"), \
             mock.patch.object(reader.source_inventory, "load_source_inventory", side_effect=AssertionError(
                 "source input must not be opened after helper substitution")):
            with self.assertRaisesRegex(ReplayError,
                "replay helper loaded outside the trusted repository: p06_managed_preflight_records"):
                fixture.replay()


if __name__ == "__main__":
    unittest.main()
