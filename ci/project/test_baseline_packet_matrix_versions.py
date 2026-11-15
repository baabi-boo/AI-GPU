# SPDX-License-Identifier: Apache-2.0
"""Reviewed matrix revisions with synthetic packets; never GPU evidence."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from baseline_matrix import validate_matrix
from baseline_packet import verify_packet
from baseline_packet_contract import _canonical
from baseline_packet_fixture import (
    CASE_IDS, SYNTHETIC, make_packet, refresh_log, save_report,
)
from baseline_packet_io import PacketError


HERE = Path(__file__).resolve().parent
ATTENTION_IDS = ("attention-tf32-simx", "attention-tf32-rtlsim")
REVISIONS = {
    "original": (
        "8c89315b2c5cb42903166f07c0c7ea96cbf95b1d3f63c708c879dbc27a8c18d5",
        "RV64 small attention catalog shape with explicit TF32, RS operand mode, "
        "NRC=8, four threads/warps/issue slots and one scalar execution block of "
        "each kind. STD scalar arithmetic and the same-shape SimX twin are "
        "explicit derived coverage.",
    ),
    "corrected": (
        "20af3af4e074ddc02020cf55a94053c93b750b802aa31cf6ebd775bf5345acea",
        "RV64 small attention catalog shape with explicit TF32, NRC=8, four "
        "threads/warps/issue slots and one scalar execution block of each kind. "
        "The kernel uses SS operands for both GEMMs; WGMMA_RS is retained in "
        "the command but is unused by this kernel. STD scalar arithmetic and "
        "the same-shape SimX twin are explicit derived coverage.",
    ),
}


def matrix_revision(revision):
    matrix = json.loads((HERE / "p01_baseline.json").read_bytes())
    for case in matrix["cases"]:
        if case["id"] in ATTENTION_IDS:
            case["derivation"] = REVISIONS[revision][1]
    return matrix


class PacketMatrixVersionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.packet_number = 0

    @staticmethod
    def write_matrix(root, report, matrix, *, compact=False):
        contents = (json.dumps(matrix, indent=None if compact else 2,
                               sort_keys=compact, allow_nan=False) + "\n").encode("utf-8")
        (root / "matrix.json").write_bytes(contents)
        report["matrix"].update(sha256=hashlib.sha256(contents).hexdigest(),
                                size_bytes=len(contents))
        return contents

    def packet(self, revision, **options):
        self.packet_number += 1
        root = self.base / ("packet-" + str(self.packet_number))
        report = make_packet(root, **options)
        matrix = matrix_revision(revision)
        self.write_matrix(root, report, matrix)
        return root, report, matrix

    def verify(self, root, report, *, required=False):
        save_report(root, report)
        return verify_packet(root, require_native_pass=required)

    def assertSummary(self, result, *, selected, passed, failed=(), not_run=(),
                      interrupted=(), outcome="pass", native=False, required=False):
        self.assertEqual(result["integrity"], "verified")
        self.assertEqual(result["run_outcome"], outcome)
        self.assertEqual(result["selected_ids"], list(selected))
        self.assertEqual(result["passed_ids"], list(passed))
        self.assertEqual(result["failed_ids"], list(failed))
        self.assertEqual(result["not_run_ids"], list(not_run))
        self.assertEqual(result["interrupted_ids"], list(interrupted))
        self.assertIs(result["native_matrix_passed"], native)
        self.assertIs(result["requirement_satisfied"], native or not required)
        self.assertEqual(result["outcome"], "pass" if native or not required else "fail")
        self.assertIs(result["phase_complete"], False)
        self.assertEqual(result["integration_outcome"], "blocked")

    def assertRejected(self, root, report, pattern="retained matrix"):
        with self.assertRaisesRegex(PacketError, pattern):
            self.verify(root, report)

    def test_reviewed_full_semantic_digests_are_exact(self):
        for revision, (expected, _) in REVISIONS.items():
            with self.subTest(revision=revision):
                matrix = matrix_revision(revision)
                self.assertIs(validate_matrix(matrix), matrix)
                self.assertEqual(hashlib.sha256(_canonical(matrix)).hexdigest(), expected)

    def test_revisions_differ_only_in_the_two_attention_descriptions(self):
        original = matrix_revision("original")
        corrected = matrix_revision("corrected")
        differences = [(old["id"], field)
                       for old, new in zip(original["cases"], corrected["cases"])
                       for field in old if old[field] != new[field]]
        self.assertEqual(differences, [(identifier, "derivation")
                                       for identifier in ATTENTION_IDS])
        comparable = deepcopy(corrected)
        for case in comparable["cases"]:
            if case["id"] in ATTENTION_IDS:
                case["derivation"] = REVISIONS["original"][1]
        self.assertEqual(original, comparable)

    def test_complete_packets_accept_both_reviewed_versions(self):
        for revision in REVISIONS:
            with self.subTest(revision=revision):
                root, report, _ = self.packet(revision)
                self.assertSummary(self.verify(root, report, required=True),
                                   selected=CASE_IDS, passed=CASE_IDS,
                                   native=True, required=True)

    def test_fresh_single_case_packets_do_not_claim_full_native_coverage(self):
        for revision in REVISIONS:
            with self.subTest(revision=revision):
                root, report, _ = self.packet(revision, selected_ids=CASE_IDS[:1])
                self.assertEqual(report["build_before"]["outcome"], "not_run")
                for required in (False, True):
                    self.assertSummary(self.verify(root, report, required=required),
                                       selected=CASE_IDS[:1], passed=CASE_IDS[:1],
                                       required=required)

    def test_attention_only_packets_keep_the_same_case_results(self):
        for revision in REVISIONS:
            with self.subTest(revision=revision):
                root, report, _ = self.packet(revision, selected_ids=ATTENTION_IDS)
                self.assertSummary(self.verify(root, report), selected=ATTENTION_IDS,
                                   passed=ATTENTION_IDS)

    def test_failed_and_blocked_attention_preserve_completed_cases_and_unrun_tail(self):
        for revision in REVISIONS:
            for outcome in ("fail", "blocked"):
                with self.subTest(revision=revision, outcome=outcome):
                    root, report, _ = self.packet(revision, failed_case=CASE_IDS[4])
                    if outcome == "blocked":
                        report["outcome"] = "blocked"
                        report["cases"][4].update(outcome="blocked", reason="launch_failed")
                        command = report["commands"][-1]
                        command.update(outcome="blocked", exit_code=None,
                                       reason="launch_failed", peak_rss_bytes=0)
                        refresh_log(root, command, SYNTHETIC + "\nlaunch blocked\n")
                    self.assertSummary(self.verify(root, report, required=True),
                                       selected=CASE_IDS, passed=CASE_IDS[:4],
                                       failed=CASE_IDS[4:5], not_run=CASE_IDS[5:],
                                       outcome=outcome, required=True)

    def test_missing_reference_success_remains_a_failed_case(self):
        for revision in REVISIONS:
            with self.subTest(revision=revision):
                root, report, _ = self.packet(revision, failed_case=CASE_IDS[4])
                command = report["commands"][-1]
                command.update(outcome="pass", exit_code=0, reason=None)
                refresh_log(root, command, SYNTHETIC + "\nFound 2 errors!\n")
                reason = "case exited successfully without its unique CPU-reference PASSED marker"
                report["reason"] = reason
                report["cases"][4].update(reason=reason, reference_marker_verified=False)
                self.assertSummary(self.verify(root, report, required=True),
                                   selected=CASE_IDS, passed=CASE_IDS[:4],
                                   failed=CASE_IDS[4:5], not_run=CASE_IDS[5:],
                                   outcome="fail", required=True)

    def test_incomplete_last_case_is_interrupted_even_after_process_success(self):
        for revision in REVISIONS:
            with self.subTest(revision=revision):
                root, report, _ = self.packet(revision, failed_case=CASE_IDS[-1])
                command = report["commands"][-1]
                command.update(outcome="pass", exit_code=0, reason=None)
                refresh_log(root, command, SYNTHETIC + "\nPASSED!\n")
                report["reason"] = "execution interrupted"
                report["cases"][-1].update(outcome="pass", reason=None)
                self.assertSummary(self.verify(root, report, required=True),
                                   selected=CASE_IDS, passed=CASE_IDS[:-1],
                                   interrupted=CASE_IDS[-1:], outcome="fail", required=True)
                report["coverage"]["full_native_matrix_passed"] = True
                self.assertRejected(root, report, "native-matrix coverage")

    def test_subset_cannot_promote_coverage_under_either_matrix_version(self):
        for revision in REVISIONS:
            for field in ("full_matrix_selected", "full_native_matrix_passed"):
                with self.subTest(revision=revision, field=field):
                    root, report, _ = self.packet(revision, selected_ids=CASE_IDS[:1])
                    report["coverage"][field] = True
                    self.assertRejected(root, report, "(?:full|native)-matrix")

    def test_json_formatting_and_object_key_order_do_not_create_new_versions(self):
        for revision in REVISIONS:
            with self.subTest(revision=revision):
                root, report, matrix = self.packet(revision)
                original = (root / "matrix.json").read_bytes()
                reformatted = self.write_matrix(root, report, matrix, compact=True)
                self.assertNotEqual(hashlib.sha256(original).digest(),
                                    hashlib.sha256(reformatted).digest())
                self.assertEqual(hashlib.sha256(_canonical(json.loads(reformatted))).hexdigest(),
                                 REVISIONS[revision][0])
                self.assertSummary(self.verify(root, report, required=True),
                                   selected=CASE_IDS, passed=CASE_IDS,
                                   native=True, required=True)

    def test_partial_description_corrections_are_not_reviewed_versions(self):
        for index in (4, 5):
            with self.subTest(corrected_case=CASE_IDS[index]):
                root, report, matrix = self.packet("original", selected_ids=CASE_IDS[:1])
                matrix["cases"][index]["derivation"] = REVISIONS["corrected"][1]
                self.assertIs(validate_matrix(matrix), matrix)
                self.write_matrix(root, report, matrix)
                self.assertRejected(root, report, "retained matrix differs")

    def test_unreviewed_prose_changes_are_rejected_even_in_unselected_cases(self):
        changes = ((0, ("derivation",), " Unreviewed description."),
                   (4, ("derivation",), " "),
                   (5, ("derivation",), " Unreviewed operand claim."),
                   (5, ("reference", "comparison"), " Unreviewed comparison."))
        for revision in REVISIONS:
            for index, fields, suffix in changes:
                with self.subTest(revision=revision, case=CASE_IDS[index], fields=fields):
                    root, report, matrix = self.packet(revision, selected_ids=CASE_IDS[1:2])
                    target = matrix["cases"][index]
                    for field in fields[:-1]:
                        target = target[field]
                    target[fields[-1]] += suffix
                    self.assertIs(validate_matrix(matrix), matrix)
                    self.write_matrix(root, report, matrix)
                    self.assertRejected(root, report, "retained matrix differs")

    def test_operational_and_numerical_drift_is_rejected_after_rehashing(self):
        changes = ((("configs", -1), "-DWGMMA_SS"),
                   (("args", 1), "64"),
                   (("reference", "tolerances", "atol"), 0.01),
                   (("reference", "tolerances", "rtol"), 0.01),
                   (("reference", "oracle"), "tests/regression/other/main.cpp"),
                   (("reference", "seed"), 51),
                   (("arithmetic", "tensor"), "DPI"))
        for revision in REVISIONS:
            for fields, value in changes:
                with self.subTest(revision=revision, fields=fields):
                    root, report, matrix = self.packet(revision, selected_ids=CASE_IDS[:1])
                    target = matrix["cases"][-1]
                    for field in fields[:-1]:
                        target = target[field]
                    target[fields[-1]] = value
                    self.write_matrix(root, report, matrix)
                    self.assertRejected(root, report)

    def test_case_and_configuration_list_reordering_is_not_a_reviewed_version(self):
        for revision in REVISIONS:
            for field in ("cases", "configs"):
                with self.subTest(revision=revision, field=field):
                    root, report, matrix = self.packet(revision, selected_ids=CASE_IDS[:1])
                    if field == "cases":
                        matrix["cases"][4:6] = reversed(matrix["cases"][4:6])
                    else:
                        matrix["cases"][-1]["configs"].reverse()
                    self.assertIs(validate_matrix(matrix), matrix)
                    self.write_matrix(root, report, matrix)
                    self.assertRejected(root, report, "retained matrix differs")


if __name__ == "__main__":
    unittest.main()
