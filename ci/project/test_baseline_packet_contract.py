# SPDX-License-Identifier: Apache-2.0
"""Independent synthetic packet checks; these tests are not GPU evidence."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from baseline_packet_contract import verify_contract
from baseline_packet_fixture import (
    CASE_IDS, SYNTHETIC, make_packet, refresh_log, refresh_stamp, save_report,
)
from baseline_packet_io import PacketError, PacketReader


class PacketContractFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.packet_number = 0

    def packet(self, **options):
        self.packet_number += 1
        root = Path(self.temporary.name) / ("packet-" + str(self.packet_number))
        return root, make_packet(root, **options)

    def verify(self, root, report):
        save_report(root, report)
        with PacketReader(root) as reader:
            observed = reader.read_json("report.json")
            matrix = reader.read_json("matrix.json")
            result = verify_contract(reader, observed, matrix)
            reader.recheck()
        return result

    def assertInvalid(self, root, report):
        with self.assertRaises(PacketError) as caught:
            self.verify(root, report)
        self.assertTrue(str(caught.exception))

    def workload(self, report, index=0):
        case_id = report["cases"][index]["id"]
        return next(command for command in report["commands"] if command["id"] == case_id)

    def assertSummary(self, summary, *, selected, passed, failed=(), not_run=(),
                      outcome="pass", native=False):
        self.assertEqual(summary["selected_ids"], list(selected))
        self.assertEqual(summary["passed_ids"], list(passed))
        self.assertEqual(summary["failed_ids"], list(failed))
        self.assertEqual(summary["not_run_ids"], list(not_run))
        self.assertEqual(summary["run_outcome"], outcome)
        self.assertIs(summary["native_matrix_passed"], native)
        self.assertIs(summary["phase_complete"], False)
        self.assertEqual(summary["integration_outcome"], "blocked")
        self.assertIsInstance(summary["limitations"], list)
        self.assertTrue(summary["limitations"])
        json.dumps(summary, allow_nan=False)

    def tooling_stages(self, report):
        for key in ("tooling_before", "tooling_before_execution", "tooling_after"):
            if key in report:
                yield report[key]
        for case in report["cases"]:
            for key in ("tooling_before", "tooling_after"):
                if key in case:
                    yield case[key]


class PacketContractAcceptanceTests(PacketContractFixture):
    def test_complete_synthetic_packet_has_native_consistency_without_phase_acceptance(self):
        root, report = self.packet()
        before = {path.relative_to(root): path.read_bytes()
                  for path in root.rglob("*") if path.is_file()}
        summary = self.verify(root, report)
        self.assertSummary(summary, selected=CASE_IDS, passed=CASE_IDS, native=True)
        self.assertEqual(summary["source_revision"], report["source_before"]["revision"])
        self.assertEqual(summary["source_tree"], report["source_before"]["tree"])
        instrumentation = report["tooling_before"]["checkout"]["revision"]
        self.assertNotEqual(instrumentation, summary["source_revision"])
        self.assertEqual(summary["instrumentation_revision"], instrumentation)
        self.assertEqual(before, {path.relative_to(root): path.read_bytes()
                                  for path in root.rglob("*") if path.is_file()})

    def test_noncontiguous_subset_preserves_canonical_order_without_full_coverage(self):
        selected = [CASE_IDS[-1], CASE_IDS[0]]
        root, report = self.packet(selected_ids=selected)
        ordered = [CASE_IDS[0], CASE_IDS[-1]]
        self.assertSummary(self.verify(root, report), selected=ordered, passed=ordered)

    def test_failed_workload_preserves_previous_pass_and_unexecuted_tail(self):
        root, report = self.packet(failed_case=CASE_IDS[1])
        self.assertSummary(self.verify(root, report), selected=CASE_IDS,
                           passed=CASE_IDS[:1], failed=CASE_IDS[1:2],
                           not_run=CASE_IDS[2:], outcome="fail")

    def test_zero_exit_with_descendants_and_incomplete_cleanup_remains_failure(self):
        root, report = self.packet(failed_case=CASE_IDS[1])
        command = self.workload(report, 1)
        command.update(exit_code=0, reason="descendants_after_exit", cleanup_complete=False)
        report["cases"][1]["reason"] = command["reason"]
        refresh_log(root, command, SYNTHETIC + "\nPASSED!\n")
        self.assertSummary(self.verify(root, report), selected=CASE_IDS,
                           passed=CASE_IDS[:1], failed=CASE_IDS[1:2],
                           not_run=CASE_IDS[2:], outcome="fail")

    def test_reference_failure_after_successful_process_is_honest_failed_record(self):
        root, report = self.packet(failed_case=CASE_IDS[1])
        command = self.workload(report, 1)
        command.update(outcome="pass", exit_code=0, reason=None)
        refresh_log(root, command, SYNTHETIC + "\nFound 2 errors!\n")
        reason = "case exited successfully without its unique CPU-reference PASSED marker"
        report["reason"] = reason
        report["cases"][1].update(reason=reason, reference_marker_verified=False)
        self.assertSummary(self.verify(root, report), selected=CASE_IDS,
                           passed=CASE_IDS[:1], failed=CASE_IDS[1:2],
                           not_run=CASE_IDS[2:], outcome="fail")

    def test_prerequisite_failure_leaves_every_case_not_run(self):
        root, report = self.packet(failed_case=CASE_IDS[0])
        fields = ("id", "app", "driver", "configs", "args", "reference", "arithmetic")
        report["cases"] = [{**{key: case[key] for key in fields},
                            "outcome": "not_run", "reason": "execution has not started",
                            "artifacts": []} for case in report["cases"]]
        report["commands"] = report["commands"][:2]
        command = report["commands"][-1]
        command.update(outcome="fail", exit_code=2, reason="nonzero_exit")
        refresh_log(root, command, SYNTHETIC + "\nsynthetic prerequisite failure\n")
        report["reason"] = "prerequisite command did not pass: kernel-library"
        self.assertSummary(self.verify(root, report), selected=CASE_IDS, passed=(),
                           not_run=CASE_IDS, outcome="fail")

    def test_source_drift_recorded_as_case_failure_does_not_become_success(self):
        root, report = self.packet(failed_case=CASE_IDS[1])
        command = self.workload(report, 1)
        command.update(outcome="pass", exit_code=0, reason=None)
        refresh_log(root, command, SYNTHETIC + "\nPASSED!\n")
        report["cases"][1]["source_after"]["revision"] = "f" * 40
        reason = "source changed during case execution"
        report["reason"] = reason
        report["cases"][1]["reason"] = reason
        self.assertSummary(self.verify(root, report), selected=CASE_IDS,
                           passed=CASE_IDS[:1], failed=CASE_IDS[1:2],
                           not_run=CASE_IDS[2:], outcome="fail")

    def test_failed_final_inventory_keeps_completed_cases_without_native_run_pass(self):
        root, report = self.packet()
        report.update(outcome="fail", reason="tool identities changed during execution")
        report["coverage"]["full_native_matrix_passed"] = False
        report["tools_after"]["tools"]["llvm_clang"]["sha256"] = "f" * 64
        for key in ("host_after", "dependencies_after", "tooling_after"):
            del report[key]
        self.assertSummary(self.verify(root, report), selected=CASE_IDS,
                           passed=CASE_IDS, outcome="fail")

    def test_original_matrix_serialization_can_differ_from_retained_snapshot(self):
        root, report = self.packet()
        retained = (root / "matrix.json").read_bytes()
        original = json.dumps(json.loads(retained), separators=(",", ":")).encode("utf-8")
        self.assertNotEqual(original, retained)
        report["matrix"].update(sha256=hashlib.sha256(original).hexdigest(),
                                size_bytes=len(original))
        self.assertSummary(self.verify(root, report), selected=CASE_IDS,
                           passed=CASE_IDS, native=True)

    def test_helper_hashes_remain_usable_without_checkout_metadata(self):
        root, report = self.packet(selected_ids=[CASE_IDS[0]])
        for stage in self.tooling_stages(report):
            stage["checkout"] = {"revision": None, "tree": None, "dirty": None}
        summary = self.verify(root, report)
        self.assertSummary(summary, selected=CASE_IDS[:1], passed=CASE_IDS[:1])
        self.assertIsNone(summary["instrumentation_revision"])

    def test_equal_log_contents_at_distinct_command_paths_are_valid(self):
        root, report = self.packet()
        for case in report["cases"]:
            command = next(item for item in report["commands"] if item["id"] == case["id"])
            refresh_log(root, command, SYNTHETIC + "\nPASSED!\n")
        self.assertSummary(self.verify(root, report), selected=CASE_IDS,
                           passed=CASE_IDS, native=True)

    def test_native_resolved_aliases_and_benign_extra_defines_are_valid(self):
        root, report = self.packet(selected_ids=[CASE_IDS[0]])
        for artifact in report["cases"][0]["configuration_artifacts"]:
            contents = (root / artifact["path"]).read_text(encoding="utf-8")
            refresh_stamp(root, artifact, contents + "CXXFLAGS: -DADDITIONAL_DIAGNOSTIC=1\n")
        self.assertSummary(self.verify(root, report), selected=CASE_IDS[:1], passed=CASE_IDS[:1])


class PacketReportContractTests(PacketContractFixture):
    def test_only_finished_run_reports_with_no_active_execution_are_accepted(self):
        mutations = (("mode", "plan"), ("state", "planned"), ("state", "running"),
                     ("state", "blocked"), ("phase_complete", True),
                     ("active_case", CASE_IDS[0]), ("active_command", "configure"))
        for key, value in mutations:
            with self.subTest(field=key, value=value):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                report[key] = value
                self.assertInvalid(root, report)

    def test_missing_required_success_fields_fail_closed(self):
        for key in ("schema_version", "finished_at", "matrix", "coverage", "cases",
                    "commands", "source_before", "tools_before", "host_before",
                    "tooling_before", "tooling_snapshots", "dependencies_before_execution"):
            with self.subTest(field=key):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                del report[key]
                self.assertInvalid(root, report)

    def test_wrong_schema_types_and_unsupported_outcomes_fail_closed(self):
        for key, value in (("schema_version", True), ("schema_version", 2),
                           ("phase_complete", 0), ("cases", {}), ("commands", None),
                           ("coverage", []), ("outcome", "not_run"),
                           ("outcome", "success"), ("outcome", "fail")):
            with self.subTest(field=key, value=value):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                report[key] = value
                self.assertInvalid(root, report)

    def test_subset_cannot_claim_full_matrix_selection_or_success(self):
        for field in ("full_matrix_selected", "full_native_matrix_passed"):
            with self.subTest(field=field):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                report["coverage"][field] = True
                self.assertInvalid(root, report)

    def test_coverage_lists_and_case_sequence_are_canonical(self):
        for mutation in ("missing_required", "duplicate_required", "reordered_required",
                         "duplicate_selected", "reordered_selected", "empty_selected",
                         "missing_case", "duplicate_case", "reordered_cases"):
            with self.subTest(mutation=mutation):
                root, report = self.packet()
                coverage = report["coverage"]
                if mutation == "missing_required":
                    coverage["required_ids"].pop()
                elif mutation == "duplicate_required":
                    coverage["required_ids"][-1] = CASE_IDS[0]
                elif mutation == "reordered_required":
                    coverage["required_ids"].reverse()
                elif mutation == "duplicate_selected":
                    coverage["selected_ids"][-1] = CASE_IDS[0]
                elif mutation == "reordered_selected":
                    coverage["selected_ids"].reverse()
                elif mutation == "empty_selected":
                    coverage["selected_ids"] = []
                elif mutation == "missing_case":
                    report["cases"].pop()
                elif mutation == "duplicate_case":
                    report["cases"][-1] = deepcopy(report["cases"][0])
                else:
                    report["cases"].reverse()
                self.assertInvalid(root, report)

    def test_case_claims_must_match_the_frozen_workload(self):
        mutations = (("app", "other_app"), ("driver", "xrt"),
                     ("args", ["-m", "128", "-n", "64", "-k", "64"]),
                     ("configs", ["-DVX_CFG_TCU_TYPE_DPI"]),
                     ("arithmetic", {"tensor": "DPI", "scalar": "STD"}),
                     ("outcome", "not_run"), ("native_flags_verified", False),
                     ("reference_marker_verified", False))
        for key, value in mutations:
            with self.subTest(field=key):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                report["cases"][0][key] = value
                self.assertInvalid(root, report)

    def test_case_reference_seed_oracle_and_tolerance_are_frozen(self):
        for field, value in (("seed", 51), ("oracle", "other/reference.cpp"),
                             ("comparison", "unreviewed comparison"),
                             ("tolerances", {"relative_error_strict_max": 1,
                                             "zero_pair_equal": True})):
            with self.subTest(field=field):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                report["cases"][0]["reference"][field] = value
                self.assertInvalid(root, report)

    def test_rehashed_matrix_cannot_change_frozen_semantics(self):
        for mutation in ("seed", "tolerance", "catalog", "shape", "dtype", "arithmetic"):
            with self.subTest(mutation=mutation):
                root, report = self.packet()
                matrix = json.loads((root / "matrix.json").read_bytes())
                for case in matrix["cases"][:2]:
                    if mutation == "seed":
                        case["reference"]["seed"] = 51
                    elif mutation == "tolerance":
                        case["reference"]["tolerances"]["relative_error_strict_max"] = 0.1
                    elif mutation == "catalog":
                        case["catalog_id"] = "sgemm_tcu-4"
                    elif mutation == "shape":
                        case["args"][1] = "128"
                    elif mutation == "dtype":
                        case["input_dtype"] = "tf32"
                    else:
                        case["arithmetic"]["tensor"] = "DPI"
                for observed, expected in zip(report["cases"], matrix["cases"]):
                    for key in ("args", "configs", "reference", "arithmetic"):
                        observed[key] = deepcopy(expected[key])
                contents = (json.dumps(matrix, indent=2) + "\n").encode("utf-8")
                (root / "matrix.json").write_bytes(contents)
                report["matrix"].update(sha256=hashlib.sha256(contents).hexdigest(),
                                        size_bytes=len(contents))
                self.assertInvalid(root, report)

    def test_matrix_identity_is_well_formed_and_bound_to_the_snapshot_id(self):
        for key, value in (("id", "p01-other"), ("sha256", "not-a-digest"),
                           ("size_bytes", True), ("size_bytes", -1)):
            with self.subTest(field=key):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                report["matrix"][key] = value
                self.assertInvalid(root, report)

    def test_vendor_integration_and_phase_claims_cannot_be_promoted(self):
        for key, value in (("outcome", "pass"), ("exit_code", 0),
                           ("driver", "rtlsim"), ("target", "hw")):
            with self.subTest(field=key):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                report["integration"][key] = value
                self.assertInvalid(root, report)


class PacketCommandContractTests(PacketContractFixture):
    def test_command_sequence_requires_each_prerequisite_configure_and_workload(self):
        for mutation in ("missing_prerequisite", "duplicate_prerequisite", "reordered",
                         "missing_case_configure", "extra_command", "duplicate_workload"):
            with self.subTest(mutation=mutation):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                commands = report["commands"]
                if mutation == "missing_prerequisite":
                    del commands[1]
                elif mutation == "duplicate_prerequisite":
                    commands.insert(2, deepcopy(commands[1]))
                elif mutation == "reordered":
                    commands[-2:] = reversed(commands[-2:])
                elif mutation == "missing_case_configure":
                    del commands[-2]
                elif mutation == "extra_command":
                    extra = deepcopy(commands[-1])
                    extra["id"] = "unexplained-command"
                    commands.append(extra)
                else:
                    commands.append(deepcopy(commands[-1]))
                self.assertInvalid(root, report)

    def test_workload_argv_is_exact_and_keeps_arguments_in_one_option(self):
        for mutation in ("driver", "app", "dimension", "split_args", "shell", "executable"):
            with self.subTest(mutation=mutation):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                argv = self.workload(report)["argv"]
                if mutation == "driver":
                    argv[1] = "--driver=rtlsim"
                elif mutation == "app":
                    argv[2] = "--app=flash_attn_tcu_wg"
                elif mutation == "dimension":
                    argv[3] = "--args=-m 128 -n 64 -k 64"
                elif mutation == "split_args":
                    argv[3:] = ["--args", "-m", "64", "-n", "64", "-k", "64"]
                elif mutation == "shell":
                    argv[3] += "; false"
                else:
                    argv[0] = "bash"
                self.assertInvalid(root, report)

    def test_prerequisite_and_case_configure_arguments_are_exact(self):
        for index in range(4):
            with self.subTest(command=index):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                report["commands"][index]["argv"].append("--unreviewed-option")
                self.assertInvalid(root, report)

    def test_command_context_rejects_changed_jobs_cache_and_config_environment(self):
        for key, value in (("MAKEFLAGS", "-j4"), ("THREADS", "4"),
                           ("CCACHE_DISABLE", "0"), ("OBJCACHE", "ccache"),
                           ("CONFIGS", "-DVX_CFG_TCU_TYPE_DPI"),
                           ("UNRECORDED_OVERRIDE", "1")):
            with self.subTest(variable=key):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                self.workload(report)["environment"][key] = value
                self.assertInvalid(root, report)
        for mutation in ("missing_configs", "cwd"):
            with self.subTest(mutation=mutation):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                command = self.workload(report)
                if mutation == "missing_configs":
                    del command["environment"]["CONFIGS"]
                else:
                    command["cwd"] = "$SOURCE"
                self.assertInvalid(root, report)

    def test_passing_command_requires_real_zero_exit_no_stop_reason_and_cleanup(self):
        for key, value in (("exit_code", 1), ("exit_code", None), ("exit_code", False),
                           ("exit_code", True), ("reason", "descendants_after_exit"),
                           ("cleanup_complete", False), ("cleanup_complete", 1),
                           ("duration_seconds", -1), ("peak_rss_bytes", True)):
            with self.subTest(field=key, value=value):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                self.workload(report)[key] = value
                self.assertInvalid(root, report)

    def test_execution_cannot_continue_after_a_failed_command(self):
        root, report = self.packet()
        command = self.workload(report)
        command.update(outcome="fail", exit_code=2, reason="nonzero_exit")
        report["cases"][0].update(outcome="fail", reason="nonzero_exit")
        report["outcome"] = "fail"
        report["coverage"]["full_native_matrix_passed"] = False
        refresh_log(root, command, SYNTHETIC + "\nFAILED!\n")
        self.assertInvalid(root, report)


class PacketRetainedEvidenceTests(PacketContractFixture):
    def test_reference_log_semantics_are_checked_after_hashes_are_refreshed(self):
        for content in ("no reference marker\n", "PASSED!\nPASSED!\n",
                        "prefix PASSED!\n", "PASSED! suffix\n",
                        "PASSED!\nFAILED!\n", "PASSED!\nFound 2 errors!\n"):
            with self.subTest(content=content):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                refresh_log(root, self.workload(report), SYNTHETIC + "\n" + content)
                self.assertInvalid(root, report)

    def test_log_bytes_digest_size_presence_and_command_binding_are_verified(self):
        for mutation in ("bytes", "digest", "size", "missing", "another_command"):
            with self.subTest(mutation=mutation):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                command = self.workload(report)
                path = root / command["log"]
                if mutation == "bytes":
                    path.write_bytes(path.read_bytes() + b"altered\n")
                elif mutation == "digest":
                    command["log_sha256"] = "f" * 64
                elif mutation == "size":
                    command["log_size_bytes"] += 1
                elif mutation == "missing":
                    path.unlink()
                else:
                    command["log"] = report["commands"][0]["log"]
                    refresh_log(root, command, SYNTHETIC + "\nPASSED!\n")
                    refresh_log(root, report["commands"][0])
                self.assertInvalid(root, report)

    def test_each_stamp_role_requires_frozen_geometry_and_rv64(self):
        for role in range(3):
            for mutation in ("missing_config", "wrong_xlen"):
                with self.subTest(role=role, mutation=mutation):
                    root, report = self.packet(selected_ids=[CASE_IDS[0]])
                    artifact = report["cases"][0]["configuration_artifacts"][role]
                    contents = (root / artifact["path"]).read_text(encoding="utf-8")
                    if mutation == "missing_config":
                        contents = contents.replace("-DVX_CFG_NUM_THREADS=8", "")
                    else:
                        contents = contents.replace("-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN=32")
                    refresh_stamp(root, artifact, contents)
                    self.assertInvalid(root, report)

    def test_native_arithmetic_and_conflicting_defines_are_checked_in_each_stamp(self):
        for role in range(3):
            for injected in ("-DVX_CFG_TCU_TYPE_DPI", "-DVX_CFG_FPU_TYPE_DPI",
                             "-DVX_CFG_TCU_TYPE=DPI", "-DVX_CFG_FPU_TYPE=DSP",
                             "-DVX_CFG_NUM_THREADS=16"):
                with self.subTest(role=role, define=injected):
                    root, report = self.packet(selected_ids=[CASE_IDS[0]])
                    artifact = report["cases"][0]["configuration_artifacts"][role]
                    contents = (root / artifact["path"]).read_text(encoding="utf-8")
                    refresh_stamp(root, artifact, contents + "CXXFLAGS: " + injected + "\n")
                    self.assertInvalid(root, report)

    def test_stamp_roles_and_source_paths_cannot_be_missing_duplicate_or_swapped(self):
        for mutation in ("missing", "duplicate", "wrong_source", "wrong_case", "source_escape"):
            with self.subTest(mutation=mutation):
                root, report = self.packet(selected_ids=CASE_IDS[:2])
                artifacts = report["cases"][0]["configuration_artifacts"]
                if mutation == "missing":
                    artifacts.pop()
                elif mutation == "duplicate":
                    artifacts[-1] = deepcopy(artifacts[0])
                elif mutation == "wrong_source":
                    artifacts[0]["source"]["path"] = "sw/runtime/simx_config.stamp"
                elif mutation == "wrong_case":
                    artifacts[0] = deepcopy(report["cases"][1]["configuration_artifacts"][0])
                else:
                    artifacts[0]["source"]["path"] = "../config.stamp"
                self.assertInvalid(root, report)

    def test_stamp_bytes_are_hashed_independently_from_redacted_source_identity(self):
        root, report = self.packet(selected_ids=[CASE_IDS[0]])
        artifact = report["cases"][0]["configuration_artifacts"][0]
        self.assertNotEqual(artifact["sha256"], artifact["source"]["sha256"])
        path = root / artifact["path"]
        path.write_bytes(path.read_bytes() + b"unrecorded content\n")
        self.assertInvalid(root, report)

    def test_binary_metadata_has_exact_roles_and_valid_identities_without_binary_files(self):
        for mutation in ("missing", "duplicate", "unknown_path", "escape", "absolute",
                         "digest", "size_type", "negative_size"):
            with self.subTest(mutation=mutation):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                identities = report["cases"][0]["binary_identities"]
                self.assertTrue(all(not (root / item["path"]).exists() for item in identities))
                if mutation == "missing":
                    identities.pop()
                elif mutation == "duplicate":
                    identities[-1] = deepcopy(identities[0])
                elif mutation == "unknown_path":
                    identities[0]["path"] = "tests/regression/other/other"
                elif mutation == "escape":
                    identities[0]["path"] = "../outside"
                elif mutation == "absolute":
                    identities[0]["path"] = "/outside"
                elif mutation == "digest":
                    identities[0]["sha256"] = "bad"
                elif mutation == "size_type":
                    identities[0]["size_bytes"] = True
                else:
                    identities[0]["size_bytes"] = -1
                self.assertInvalid(root, report)


class PacketProvenanceContractTests(PacketContractFixture):
    def test_passing_case_source_before_and_after_match_initial_clean_identity(self):
        for stage in ("source_before", "source_after"):
            for mutation in ("revision", "tree", "pin", "submodule", "input", "dirty", "outcome"):
                with self.subTest(stage=stage, mutation=mutation):
                    root, report = self.packet(selected_ids=[CASE_IDS[0]])
                    source = report["cases"][0][stage]
                    if mutation in ("revision", "tree"):
                        source[mutation] = "f" * 40
                    elif mutation == "pin":
                        source["pins"]["TOOLCHAIN_REV"] = "v0.0.0"
                    elif mutation == "submodule":
                        source["submodules"]["entries"][0]["revision"] = "f" * 40
                    elif mutation == "input":
                        source["inputs"][0]["sha256"] = "f" * 64
                    elif mutation == "dirty":
                        source["dirty"] = True
                    else:
                        source["outcome"] = "blocked"
                    self.assertInvalid(root, report)

    def test_success_requires_clean_initial_source_and_complete_submodule_inventory(self):
        for mutation in ("revision", "tree", "dirty", "changed_paths", "missing_submodule",
                         "duplicate_submodule", "missing_input"):
            with self.subTest(mutation=mutation):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                source = report["source_before"]
                if mutation in ("revision", "tree"):
                    source[mutation] = "malformed"
                elif mutation == "dirty":
                    source["dirty"] = True
                elif mutation == "changed_paths":
                    source["changed_paths"] = ["VX_config.toml"]
                elif mutation == "missing_submodule":
                    source["submodules"]["entries"].pop()
                elif mutation == "duplicate_submodule":
                    entries = source["submodules"]["entries"]
                    entries[-1] = deepcopy(entries[0])
                else:
                    source["inputs"].pop()
                self.assertInvalid(root, report)

    def test_build_snapshots_cannot_change_xlen_native_source_or_copied_inputs(self):
        for stage in ("build_before", "build_after"):
            for mutation in ("xlen", "identity_matches", "source_inputs", "build_inputs",
                             "source_build_inputs", "generated"):
                with self.subTest(stage=stage, mutation=mutation):
                    root, report = self.packet(selected_ids=[CASE_IDS[0]])
                    build = report["cases"][0][stage]
                    if mutation == "xlen":
                        build["xlen"] = 32
                    elif mutation == "identity_matches":
                        build["identity_matches"] = False
                    else:
                        build[mutation][0]["sha256"] = "f" * 64
                    self.assertInvalid(root, report)

    def test_dependencies_remain_bound_at_every_execution_boundary(self):
        for stage in ("dependencies_before", "dependencies_at_launch", "dependencies_after"):
            with self.subTest(stage=stage):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                report["cases"][0][stage]["artifacts"][0]["sha256"] = "f" * 64
                self.assertInvalid(root, report)
        for stage in ("dependencies_planned", "dependencies_before_execution", "dependencies_after"):
            with self.subTest(stage=stage):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                report[stage]["artifacts"][0]["sha256"] = "f" * 64
                self.assertInvalid(root, report)

    def test_retained_helper_hashes_bind_to_the_recorded_executing_files(self):
        for refresh in (False, True):
            with self.subTest(refresh_snapshot=refresh):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                snapshot = report["tooling_snapshots"][0]
                path = root / snapshot["path"]
                contents = path.read_bytes() + b"# altered inert helper\n"
                path.write_bytes(contents)
                if refresh:
                    snapshot.update(sha256=hashlib.sha256(contents).hexdigest(),
                                    size_bytes=len(contents))
                self.assertInvalid(root, report)

    def test_executing_helper_identities_cannot_drift_after_snapshotting(self):
        for stage in ("tooling_before", "tooling_after"):
            with self.subTest(stage=stage):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                report["cases"][0][stage]["files"][0]["sha256"] = "f" * 64
                self.assertInvalid(root, report)
        for stage in ("tooling_before_execution", "tooling_after"):
            with self.subTest(stage=stage):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                report[stage]["files"][0]["sha256"] = "f" * 64
                self.assertInvalid(root, report)

    def test_success_requires_stable_host_and_tool_identities(self):
        for stage in ("host_before_execution", "host_after"):
            with self.subTest(stage=stage):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                report[stage]["tools"]["g++"]["sha256"] = "f" * 64
                self.assertInvalid(root, report)
        root, report = self.packet(selected_ids=[CASE_IDS[0]])
        report["tools_after"]["tools"]["llvm_clang"]["sha256"] = "f" * 64
        self.assertInvalid(root, report)

    def test_success_requires_case_after_snapshots_and_final_inventories(self):
        for field in ("source_after", "build_after", "dependencies_after", "tooling_after"):
            with self.subTest(case_field=field):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                del report["cases"][0][field]
                self.assertInvalid(root, report)
        for field in ("tools_after", "host_after", "dependencies_after", "tooling_after"):
            with self.subTest(report_field=field):
                root, report = self.packet(selected_ids=[CASE_IDS[0]])
                del report[field]
                self.assertInvalid(root, report)


if __name__ == "__main__":
    unittest.main()
